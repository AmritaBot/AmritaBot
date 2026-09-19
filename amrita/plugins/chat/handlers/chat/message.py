"""消息合成与格式化（从原 chat.py 抽出）。

职责：
- 用户输入转义 / legacy / XML 两种消息格式渲染
- 引用消息（Reply）展开为可读上下文
- 引用图片提取
- 用户角色获取
- 将事件消息合成为 ChatObject 输入（含多模态判定）

多模态约定：图片二进制一律先本地落库（``utils/context_store.py``），
上下文里只放 ``PlaceholderContent`` 占位符；体积超限的图片直接丢弃。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from amrita_core import TextContent, debug_log
from amrita_core.types import Content
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from nonebot.adapters.onebot.v11.event import MessageEvent, Reply

from ...config import config_manager
from ...utils.context_store import PlaceholderContent, store_media
from ...utils.format import (
    escape_content,
    escape_xml,
    escape_xml_attr,
    format_msg_legacy,
    format_msg_xml,
)
from ...utils.functions import format_current_datetime, synthesize_message
from ...utils.net_guard import (
    FetchResult,
    decode_inline_bytes,
    fetch_remote_bytes,
    file_url_to_path,
    read_local_bytes,
)
from ...utils.preset import resolve_preset
from ...utils.sql import get_uni_user_id

#  单张图片下载超时（秒）
_IMAGE_DOWNLOAD_TIMEOUT = 30
#  max_image_kb 配置为 0（不限制）时的兜底硬上限（字节），避免单张图片打爆内存
_HARD_MAX_IMAGE_BYTES = 32 * 1024 * 1024
#  受支持的图片格式（文件头 -> MIME）。白名单式匹配，识别不出的内容一律丢弃。
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def _max_image_bytes() -> int:
    """当前配置允许的单张图片体积上限（字节）。"""
    limit_kb = config_manager.config.context.max_image_kb
    return _HARD_MAX_IMAGE_BYTES if limit_kb <= 0 else limit_kb * 1024


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
        # 用户消息内容也需要转义，因为 downstream format_msg_xml
        # 在检测到已有 <ref> 后会跳过二次转义
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


def _sniff_mime(raw: bytes) -> str | None:
    """根据文件头推断图片 MIME 类型（比 Content-Type 可靠）。

    识别不出时返回 ``None``，调用方应丢弃该数据。绝不"猜不到就当 jpeg"：
    否则被诱导读到的非图片内容（如文本文件）会被当作图片送进模型。
    """
    for signature, mime in _IMAGE_SIGNATURES:
        if raw.startswith(signature):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[4:8] == b"ftyp":
        brand = raw[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"):
            return "image/heic"
    return None


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


async def _fetch_image_bytes(bot: Bot, seg: MessageSegment) -> _ImageFetchResult:
    """获取图片二进制与 MIME 类型。

    消息段中的 ``url`` / ``file`` 是**客户端可控的不可信输入**，因此：

    - 远程地址一律经 :func:`~amrita.plugins.chat.utils.net_guard.fetch_remote_bytes`
      做 SSRF 校验（仅公网地址）与限流下载；
    - 本地文件只允许读取 ``context.local_media_dirs`` 白名单目录内的常规文件，
      防止 ``file:///etc/passwd`` 之类的任意文件读取；
    - 所有分支都受 ``context.max_image_kb`` 限制，超限直接丢弃；
    - 内容必须能被识别为受支持的图片格式，否则丢弃（防止非图片数据外泄）。

    失败时不抛异常，而是返回带 ``summary`` 的结果（最后一个候选地址的失败原因）。
    """
    limit = _max_image_bytes()
    candidates: list[str] = []
    if url := str(seg.data.get("url") or ""):
        candidates.append(url)
    elif file := seg.data.get("file"):
        try:
            info = await bot.get_image(file=str(file))
        except Exception:
            logger.opt(exception=True).debug(
                f"调用 get_image 获取图片信息失败: {file!r}"
            )
        else:
            #  优先用服务端给出的 url，其次是本地文件路径
            candidates.extend(
                str(value)
                for key in ("url", "file")
                if (value := info.get(key)) is not None
            )
    if not candidates:
        debug_log("图片消息段缺少可用的 url，已跳过")
        return _ImageFetchResult(summary="消息段未提供可用的图片地址")

    reason = "图片不可用"
    for candidate in candidates:
        try:
            result = await _resolve_media_bytes(candidate, limit)
        except Exception:
            logger.opt(exception=True).warning(f"获取图片二进制异常: {candidate!r}")
            reason = "下载图片时发生未预期异常"
            continue
        if (raw := result.data) is None:
            reason = result.reason or reason
            continue
        mime = _sniff_mime(raw)
        if mime is None:
            debug_log("图片内容不是受支持的图片格式，已丢弃")
            reason = "内容不是受支持的图片格式"
            continue
        return _ImageFetchResult(raw=raw, mime=mime)
    return _ImageFetchResult(summary=reason)


async def _build_image_contents(
    bot: Bot, message: Iterable[MessageSegment], uni_id: str
) -> list[Content]:
    """采集消息段中的图片：成功时本地落库并返回占位符，失败时回写一条说明文本。

    失败（下载失败、被安全策略拒绝、体积超限、格式不支持、落库被拒）不会中断流程，
    而是 warn 记录后以 ``TextContent`` 的形式写回上下文，让模型知道
    "这里本来有一张图但没拿到"，而不是凭空少一段内容导致误判。
    """
    contents: list[Content] = []
    for seg in message:
        if seg.type != "image":
            continue
        result = await _fetch_image_bytes(bot, seg)
        if not result.ok:
            logger.warning(f"图片获取失败，已跳过该图片：{result.summary}")
            contents.append(TextContent(text=f"[图片不可用：{result.summary}]"))
            continue
        media_id = await store_media(uni_id=uni_id, raw=result.raw, mime=result.mime)
        if media_id is None:
            limit_kb = config_manager.config.context.max_image_kb
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


async def _is_multimodal() -> bool:
    """当前主预设或任一备选预设是否启用多模态。"""
    presets = [
        await resolve_preset(preset)
        for preset in [
            config_manager.config.preset,
            *config_manager.config.preset_extension.backup_preset_list,
        ]
    ]
    return any(p.config.multimodal for p in presets)


async def get_reply_pics(bot: Bot, event: MessageEvent) -> list[Content]:
    """获取引用消息中的图片内容（本地落库后以占位符形式返回）

    采集失败的图片会以说明文本的形式一并返回，避免引用内容凭空缺失。

    Returns:
        图片占位符（及失败说明文本）列表
    """
    if not (reply := event.reply):
        return []
    if not await _is_multimodal():
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
    is_multimodal: bool = await _is_multimodal()

    if config_manager.config.parse_segments:
        #  时间戳让模型能判断消息先后与间隔；两种格式都带
        now = format_current_datetime()
        if config_manager.config.function.message_type == "xml":
            # handle_reply 在 XML 模式下已对 content 做了 escape_xml，
            # 且 content 中可能包含 <ref> 标签（已转义好的引用内容），
            # 因此不能再次经过 format_msg_xml 的转义导致双重转义
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
