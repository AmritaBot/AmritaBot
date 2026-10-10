"""消息合成与格式化（从原 chat.py 抽出）。

职责：
- 用户输入转义 / legacy / XML 两种消息格式渲染
- 引用消息（Reply）展开为可读上下文
- 引用图片提取
- 用户角色获取
- 将事件消息合成为 ChatObject 输入（含多模态判定）

多模态约定：图片二进制一律先经 ``utils/image_norm.py`` 归一化（解码校验、等比缩小、
转码为模型支持的格式、压缩到 ``max_allowed_size`` 以内），再本地落库
（``utils/context_store.py``），上下文里只放 ``PlaceholderContent`` 占位符。

两道体积闸职责不同：``max_image_kb`` 是**下载闸**（只管拉取，可放宽让手机原图
进来被缩放）；``max_allowed_size`` 是**上下文闸**（管最终存入上下文的单张图）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from amrita_core import TextContent, debug_log
from amrita_core.types import USER_INPUT, Content
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, MessageEvent, Reply

from ...config import HARD_MAX_IMAGE_BYTES, config_manager
from ...utils.context_store import PlaceholderContent, store_media
from ...utils.format import (
    escape_content,
    escape_xml,
    escape_xml_attr,
    format_msg_legacy,
    format_msg_xml,
)
from ...utils.functions import (
    format_current_datetime,
    get_friend_name,
    synthesize_message,
)
from ...utils.image_norm import normalize_image
from ...utils.net_guard import (
    FetchResult,
    decode_inline_bytes,
    fetch_remote_bytes,
    file_url_to_path,
    read_local_bytes,
)
from ...utils.preset import is_multimodal_enabled
from ...utils.sql import get_uni_user_id

#  单张图片下载超时（秒）
_IMAGE_DOWNLOAD_TIMEOUT = 30


def _max_image_bytes() -> int:
    """下载闸：允许拉取的单张图片体积上限（字节）。

    只约束网络 / 本地读取。真正存入上下文的大小由 ``context.max_allowed_size``
    在归一化后决定，因此这个上限可以放宽，让手机原图有机会被缩放后再用。
    ``max_image_kb`` 为 0（不限制）时回落到 :data:`HARD_MAX_IMAGE_BYTES`，
    避免单张图片打爆内存。
    """
    limit_kb = config_manager.config.context.max_image_kb
    return HARD_MAX_IMAGE_BYTES if limit_kb <= 0 else limit_kb * 1024


async def _normalize(raw: bytes) -> tuple[bytes, str] | str:
    """归一化图片二进制，返回 ``(raw, mime)``；失败时返回一句说明文本。

    体积上限传的是**上下文闸**：归一化负责把图压到达标，否则 ``store_media``
    会直接拒掉一张本可以被缩放、降质后正常使用的图。

    Pillow 解码是 CPU 密集操作，放到线程里执行，避免阻塞事件循环。
    """
    context = config_manager.config.context
    result = await asyncio.to_thread(
        normalize_image,
        raw,
        max_width=context.max_image_width,
        max_height=context.max_image_height,
        max_bytes=context.max_allowed_size * 1024
        if context.max_allowed_size > 0
        else 0,
    )
    if not result.ok:
        return result.reason
    return result.raw, result.mime


@dataclass(frozen=True, slots=True)
class _ImageFetchResult:
    """单张图片的采集结果。

    成功时 ``raw`` / ``mime`` 有值；失败时 ``summary`` 是一句可回写上下文的简短说明，
    调用方据此跳过该图片并把“这里本来有张图但没拿到”告知模型。
    """

    raw: bytes = b""
    mime: str = ""
    summary: str = ""

    @property
    def ok(self) -> bool:
        """是否成功取到图片二进制与 MIME。"""
        return bool(self.raw) and bool(self.mime)


async def handle_reply(
    reply: Reply, bot: Bot, group_id: int | None, content: str
) -> str:
    """处理引用消息：
    - 提取引用消息的内容和时间信息。
    - 格式化为可读的引用内容。

    Args:
        reply: 回复消息
        bot: Bot实例
        group_id: 群组ID（私聊为None）
        content: 原始内容

    Returns:
        格式化后的内容
    """
    if not reply.sender.user_id:
        return content
    dt_object = datetime.fromtimestamp(reply.time)
    weekday = dt_object.strftime("%A")
    formatted_time = dt_object.strftime("%Y-%m-%d %I:%M:%S %p")
    role = (
        f"{await get_user_role(bot, group_id, reply.sender.user_id)}"
        if group_id
        else ""
    )

    reply_content = await synthesize_message(reply.message, bot)
    safe_name = reply.sender.nickname or ""
    msg_type = config_manager.config.function.message_type

    if msg_type == "xml":
        safe_content = escape_xml(reply_content)
        # 昵称进的是属性值，需要额外转义双引号，否则可以伪造属性
        safe_name = escape_xml_attr(safe_name)
        # 用户消息内容也需要转义：format_msg_xml 检测到已有 <ref> 后会跳过二次转义
        safe_user_content = escape_xml(content)
        result = (
            f"{safe_user_content}\n"
            f'<ref name="{safe_name}" uid="{reply.sender.user_id}">\n'
            f"  <time>{formatted_time} {weekday}</time>\n"
            f"  <content>{safe_content}</content>\n"
            f"</ref>"
        )
    else:
        safe_content = escape_content(reply_content)
        safe_name = escape_content(safe_name)
        result = f"{content}\n<MESSAGE_REFERED>\n{formatted_time} {weekday} {role}{safe_name}（QQ:{reply.sender.user_id}）说：{safe_content}\n</MESSAGE_REFERED>"
    debug_log(f"处理引用消息完成: {result[:50]}..")
    return result


async def _resolve_media_bytes(value: str, limit: int) -> FetchResult:
    """按来源类型取出二进制数据。

    - ``http(s)://``：经 SSRF 校验与限流下载；
    - ``base64://`` / ``data:<mime>;base64,``：内联解码（带体积上限）；
    - ``file://`` 或裸路径：仅允许 ``context.local_media_dirs`` 白名单目录内的常规文件；
    - 其它协议（ftp、gopher、UNC 等）一律拒绝。

    失败时返回带 ``reason`` 的结果，供调用方记录日志并回写上下文。
    """
    if value.startswith(("http://", "https://")):
        return await fetch_remote_bytes(
            value, max_bytes=limit, timeout=_IMAGE_DOWNLOAD_TIMEOUT
        )
    if value.startswith(("data:", "base64://")):
        raw = decode_inline_bytes(value, max_bytes=limit)
        if raw is None:
            return FetchResult(reason="内联图片数据无法解码或超出体积上限")
        return FetchResult(data=raw)
    if value.startswith("file://"):
        path = file_url_to_path(value)
        if path is None:
            return FetchResult(reason="不允许访问非本机的 file 地址")
    elif "://" in value:
        scheme = value.split("://", 1)[0]
        logger.debug(f"已拒绝不支持的图片地址协议: {value!r}")
        return FetchResult(reason=f"不支持的图片地址协议（{scheme}）")
    else:
        path = value
    raw = await asyncio.to_thread(
        read_local_bytes,
        path,
        allowed_dirs=config_manager.config.context.local_media_dirs,
        max_bytes=limit,
    )
    if raw is None:
        return FetchResult(reason="本地文件不可读、不在允许目录内或超出体积上限")
    return FetchResult(data=raw)


async def _try_image_source(value: str, limit: int) -> _ImageFetchResult:
    """尝试把单个候选地址取成图片。

    成功返回二进制与 MIME，失败返回带 ``summary`` 的结果（不抛异常）。
    """
    try:
        result = await _resolve_media_bytes(value, limit)
    except Exception:
        logger.opt(exception=True).warning(f"获取图片二进制异常: {value!r}")
        return _ImageFetchResult(summary="下载图片时发生未预期异常")
    if (raw := result.data) is None:
        return _ImageFetchResult(summary=result.reason or "图片不可用")
    #  必须真正解码一次：文件头可以被伪造，只有解码能识破伪装成图片的任意数据
    normalized = await _normalize(raw)
    if isinstance(normalized, str):
        debug_log(f"图片归一化失败，已丢弃：{normalized}")
        return _ImageFetchResult(summary=normalized)
    return _ImageFetchResult(raw=normalized[0], mime=normalized[1])


async def _image_candidates(bot: Bot, seg: MessageSegment) -> AsyncIterator[str]:
    """按优先级产出候选地址。

    消息段里的 ``url`` 与 ``file`` 可能同时存在（``url`` 可能已过期），
    所以两者都是候选，不能因为拿到了 ``url`` 就放弃 ``file``；
    查询 ``file`` 需要一次协议端往返，因此排在 ``url`` 之后惰性执行。
    """
    if url := str(seg.data.get("url") or ""):
        yield url
    file = seg.data.get("file")
    if not file:
        return
    try:
        info = await bot.get_image(file=str(file))
    except Exception:
        logger.opt(exception=True).debug(f"调用 get_image 获取图片信息失败: {file!r}")
        return
    #  优先用服务端给出的 url，其次是本地文件路径
    for key in ("url", "file"):
        if (value := info.get(key)) is not None:
            yield str(value)


async def _fetch_image_bytes(bot: Bot, seg: MessageSegment) -> _ImageFetchResult:
    """获取图片二进制与 MIME 类型。

    消息段中的 ``url`` / ``file`` 是**客户端可控的不可信输入**，因此：

    - 远程地址一律经 :func:`~amrita.plugins.chat.utils.net_guard.fetch_remote_bytes`
      做 SSRF 校验（仅公网地址）与限流下载；
    - 本地文件只允许读取 ``context.local_media_dirs`` 白名单目录内的常规文件，
      防止 ``file:///etc/passwd`` 之类的任意文件读取；
    - 所有分支都受 ``context.max_image_kb``（下载闸）限制，超限直接丢弃；
    - 取到的内容必须能被 Pillow 真正解码为受支持的图片，否则丢弃
      （防止非图片数据外泄，也拦住伪装成图片的任意内容）；
    - 解码后按 ``context.max_image_width`` / ``max_image_height`` 等比缩小，
      把不受模型支持的格式转码，并压缩到 ``context.max_allowed_size`` 以内，
      见 :mod:`amrita.plugins.chat.utils.image_norm`。

    失败时不抛异常，而是返回带 ``summary`` 的结果（最后一个候选地址的失败原因）。
    """
    limit = _max_image_bytes()
    reason = "图片不可用"
    has_candidate = False
    async for candidate in _image_candidates(bot, seg):
        has_candidate = True
        result = await _try_image_source(candidate, limit)
        if result.ok:
            return result
        reason = result.summary or reason
    if not has_candidate:
        debug_log("图片消息段缺少可用的 url，已跳过")
        return _ImageFetchResult(summary="消息段未提供可用的图片地址")
    return _ImageFetchResult(summary=reason)


async def _build_image_contents(
    bot: Bot, message: Iterable[MessageSegment], uni_id: str
) -> list[Content]:
    """采集消息段中的图片：成功时本地落库并返回占位符，失败时回写一条说明文本。

    失败（下载失败、被安全策略拒绝、体积超限、解码失败、落库被拒）不会中断流程，
    而是 warn 记录后以 ``TextContent`` 的形式写回上下文，让模型知道
    "这里本来有一张图但没拿到"，而不是凭空少一段内容导致误判。

    单条消息的图片数量受 ``context.max_images_per_message`` 约束。超出后**立即停止**，
    不再下载后续图片：否则一条塞满图片段的消息就能让我们做任意多次网络往返。

    配额计的是**已检视的图片段**，而不是成功入库的张数：后者意味着失败 / 被拒的
    图片段不占名额，一条全是坏图的消息仍会触发无上限的下载。
    """
    contents: list[Content] = []
    limit = config_manager.config.context.max_images_per_message
    inspected = 0
    for seg in message:
        if seg.type != "image":
            continue
        if limit > 0 and inspected >= limit:
            logger.warning(f"单条消息图片数量超出上限 {limit}，已忽略后续图片")
            contents.append(
                TextContent(text=f"[图片已忽略：单条消息最多 {limit} 张图片]")
            )
            break
        #  先计数再下载：配额约束的是网络开销，与后续成败无关
        inspected += 1
        result = await _fetch_image_bytes(bot, seg)
        if not result.ok:
            logger.warning(f"图片获取失败，已跳过该图片：{result.summary}")
            contents.append(TextContent(text=f"[图片不可用：{result.summary}]"))
            continue
        media_id = await store_media(uni_id=uni_id, raw=result.raw, mime=result.mime)
        if media_id is None:
            limit_kb = config_manager.config.context.max_allowed_size
            reason = f"体积超出上限 {limit_kb}KB" if limit_kb > 0 else "内容为空"
            logger.warning(f"图片落库被拒绝，已跳过该图片：{reason}")
            contents.append(TextContent(text=f"[图片已丢弃：{reason}]"))
            continue
        contents.append(
            PlaceholderContent(
                media_id=media_id,
                kind="image",
                mime=result.mime,
                size=len(result.raw),
            )
        )
    return contents


async def get_reply_pics(bot: Bot, event: MessageEvent) -> list[Content]:
    """获取引用消息中的图片内容（本地落库后以占位符形式返回）

    采集失败的图片会以说明文本的形式一并返回，避免引用内容凭空缺失。

    Returns:
        图片占位符（及失败说明文本）列表
    """
    if not (reply := event.reply):
        return []
    if not await is_multimodal_enabled():
        return []
    images = await _build_image_contents(bot, reply.message, get_uni_user_id(event))
    pics = sum(1 for item in images if isinstance(item, PlaceholderContent))
    debug_log(f"获取引用图片完成，成功 {pics} 张，失败 {len(images) - pics} 张")
    return images


async def get_user_role(bot: Bot, group_id: int, user_id: int) -> str:
    """获取用户在群聊中的身份（群主、管理员或普通成员）。

    Args:
        group_id: 群组ID
        user_id: 用户ID

    Returns:
        用户角色字符串
    """
    role_data = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    role = role_data["role"]
    role_str = {"admin": "群管理员", "owner": "群主", "member": "普通成员"}.get(
        role, "[获取身份失败]"
    )
    debug_log(f"获取用户角色完成: {role_str}")
    return role_str


async def synthesize_message_to_msg(
    event: MessageEvent,
    role: str,
    user_name: str,
    user_id: str,
    content: str,
    bot: Bot,
) -> Sequence[Content] | str:
    """将消息转换为Message

    根据配置和多模态支持情况，将事件消息转换为适当的格式，
    支持文本和图片内容的组合（图片以本地落库的占位符形式出现）。

    Args:
        event: 消息事件
        role: 用户角色
        user_name: 用户名
        user_id: 用户ID
        content: 消息内容
        bot: Bot 实例（下载图片用）

    Returns:
        转换后的消息内容
    """
    is_multimodal: bool = await is_multimodal_enabled()

    if config_manager.config.parse_segments:
        #  时间戳让模型能判断消息先后与间隔；两种格式都带
        now = format_current_datetime()
        if config_manager.config.function.message_type == "xml":
            # handle_reply 在 XML 模式下已对 content 做 escape_xml（可能含 <ref>），不能再转义一次
            body = format_msg_xml(
                role,
                str(user_name),
                str(user_id),
                content,
                time=now,
                content_escaped="\n<ref" in content,
            )
        else:
            body = format_msg_legacy(
                role, str(user_name), str(user_id), content, time=now
            )
        text: Sequence[Content] | str = (
            [
                TextContent(text=body),
                *await _build_image_contents(
                    bot, event.message, get_uni_user_id(event)
                ),
            ]
            if is_multimodal
            else body
        )
    else:
        text = event.message.extract_plain_text()
    return text


async def build_user_input(event: MessageEvent, bot: Bot) -> USER_INPUT:
    """把单个消息事件合成为一条用户输入（含引用展开与图片占位）。

    防抖批次内每条消息各调用一次，各自的 XML/legacy 结构与时间戳都会保留。
    """
    is_group = isinstance(event, GroupMessageEvent)
    content: str = await synthesize_message(event.get_message(), bot)
    if content.strip() == "":
        content = ""
    if event.reply:
        group_id = event.group_id if is_group else None
        debug_log("处理引用消息..")
        content = await handle_reply(event.reply, bot, group_id, content)

    reply_pics = await get_reply_pics(bot, event)
    debug_log(f"获取引用图片完成，共 {len(reply_pics)} 张")

    if is_group:
        debug_log("处理群聊消息")
        user_name = (
            (
                await bot.get_group_member_info(
                    group_id=event.group_id, user_id=event.user_id
                )
            )["nickname"]
            if not config_manager.config.function.use_user_nickname
            else event.sender.nickname
        )
    else:
        debug_log("处理私聊消息")
        user_name = await get_friend_name(event.user_id, bot=bot)
    role = await get_user_role(bot, event.group_id, event.user_id) if is_group else ""
    result: USER_INPUT = await synthesize_message_to_msg(
        event, role, str(user_name), str(event.user_id), content, bot
    )
    if isinstance(result, list):
        result.extend(reply_pics)
    return result


def merge_user_inputs(parts: Sequence[USER_INPUT]) -> USER_INPUT:
    """把同一防抖批次的用户输入合并成一条。

    纯文本批次直接换行拼接；含富内容时摊平成 Content 列表，每条消息结构与时间戳原样保留。
    """
    if len(parts) == 1:
        return parts[0]
    texts = [part for part in parts if isinstance(part, str)]
    if len(texts) == len(parts):
        return "\n".join(text for text in texts if text)
    merged: list[Content] = []
    for part in parts:
        if isinstance(part, str):
            if part:
                merged.append(TextContent(text=part))
        elif part is not None:
            merged.extend(part)
    return merged
