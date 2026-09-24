"""群聊上下文静默存储 / 多模态本地存储服务层。

本模块是"上下文静默存储"架构的唯一出入口，向上提供：

- :func:`append_context_record` —— 把一条未被触发的群消息静默落库（替代写入记忆）
- :func:`read_context_records` —— 供 ``read_context`` 工具按需读取
- :func:`store_media` —— 多模态二进制落库，返回占位符所需的 ``media_id``
- :func:`resolve_placeholders_in_messages` / :func:`resolve_placeholders_in_content`
  —— 读路径：占位符 -> ``data:<mime>;base64,...`` 的 ``ImageContent``
  （前者返回**新列表**，不修改传入的消息对象）
- :func:`collapse_media_to_placeholders` —— 写路径：把 base64 的 ``ImageContent``
  折叠回占位符，保证数据库里只存占位符

设计约束（重要）：**"记忆里只有占位符"必须是不变式，而不是"顺利的话"的副作用**。

1. 展开只作用于副本。``resolve_placeholders_in_messages`` 返回新列表，调用方
   （``ChatMemoryBackend.load_memory``）把它挂到一份 ``model_copy()`` 上。若就地
   改写共享的 ``CachedUserDataRepository._cached_memory``，一旦本次运行在
   ``COMMIT_MEMORY`` 之前中断（LLM 报错 / 超时 / 取消，它是工作流最后一个节点），
   缓存里残留的 base64 就会被后续任意"读缓存 + 写库"的命令（``/prompt set``、
   ``/session compact`` 等）持久化进 ``memory_json``。
2. 折叠只看内容。data URI 合法即折回占位符，不查询 :class:`ContextMedia` 是否
   还在：媒体可能已被 TTL 淘汰，此时若不折叠，base64 同样会被写进记忆。
3. 任何绕过 ``ChatMemoryBackend.commit_memory`` 的写库路径都必须经
   ``utils/data_access.py:update_memory``（它内部会先折叠）。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import time
from collections.abc import Iterable
from datetime import datetime, timedelta

import aiologic
from amrita_core.types import (
    CONTENT_LIST_TYPE_ITEM,
    USER_INPUT,
    Content,
    ImageContent,
    ImageUrl,
    Message,
    TextContent,
)
from nonebot import logger
from nonebot_plugin_orm import AsyncSession, get_session
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from amrita.cache import WeakValueLRUCache

from ..config import HARD_MAX_IMAGE_BYTES, config_manager
from ..models import ContextMedia, ContextRecord, PlaceholderContent

__all__ = [
    "PlaceholderContent",
    "append_context_record",
    "collapse_media_to_placeholders",
    "has_placeholders",
    "load_media_data_uri",
    "omit_placeholders_in_messages",
    "prune_context_store",
    "read_context_records",
    "resolve_placeholders_in_content",
    "resolve_placeholders_in_messages",
    "store_media",
]

#  MIME 类型白名单式校验：只允许形如 ``type/subtype`` 的简单结构，
#  防止不可信字符串拼进 ``data:<mime>;base64,`` 时破坏 URI 结构（参数注入）。
_MIME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}$"
)

#  data URI 解码后的体积硬上限（字节），避免超长负载撑爆内存
_MAX_DECODED_BYTES = HARD_MAX_IMAGE_BYTES
#  data URI 文本的硬上限（base64 膨胀系数 4/3，再加少量前缀余量）
_MAX_DATA_URI_LENGTH = (_MAX_DECODED_BYTES // 3 + 1) * 4 + 64

#  上一次执行淘汰任务的时间（``time.monotonic()``），节流间隔由配置决定
_last_prune_at: float = 0.0
#  动态锁池：按资源键（会话 / media_id）分配锁，弱引用保证无人在用时自动回收
_lock_pool: WeakValueLRUCache[str, aiologic.Lock] = WeakValueLRUCache(
    capacity=2048, loose_mode=True
)
#  淘汰任务的全局串行锁：避免节流检查与执行被并发穿插（多个协程同时全表删除）
_prune_lock: aiologic.Lock = aiologic.Lock()

#  本轮由占位符展开出来的 media_id（内容寻址）。
#  折叠时用它区分两种情况：即便对应行已被 TTL 淘汰，只要是本插件自己展开出来的
#  内容就必须折回占位符，否则 base64 会被写进记忆表；而来源不明的 data URI 保持
#  原样，避免静默丢弃。容量有上限，超出即整体清空（只需保证最近一批还在）。
_EXPANDED_ID_LIMIT = 4096
_expanded_ids: set[str] = set()


def _remember_expanded(media_id: str) -> None:
    if len(_expanded_ids) >= _EXPANDED_ID_LIMIT:
        _expanded_ids.clear()
    _expanded_ids.add(media_id)


def _lock_for(key: str) -> aiologic.Lock:
    """取（或创建）``key`` 对应的锁，用于串行化同一资源的“查-改-写”。"""
    if (lock := _lock_pool.get(key)) is None:
        lock = aiologic.Lock()
        _lock_pool.put(key, lock)
    return lock


def _prune_interval_seconds() -> float:
    """淘汰任务的节流间隔（秒）；配置为 0 时不节流。"""
    return config_manager.config.context.prune_interval_minutes * 60.0


def _sanitize_mime(mime: str) -> str:
    """校验 MIME 格式，不合法时回落到 ``application/octet-stream``。"""
    return mime if _MIME_PATTERN.fullmatch(mime) else "application/octet-stream"


def _decode_data_uri(url: str) -> tuple[str, str, bytes] | None:
    """把 ``data:<mime>;base64,<payload>`` 解析为 ``(mime, sha256, raw)``。

    使用 ``partition`` 线性切分而非正则匹配，避免超长恶意负载触发回溯型 ReDoS；
    同时在解码前先按文本长度做体积预检。
    """
    if len(url) > _MAX_DATA_URI_LENGTH:
        logger.debug("data URI 长度超出上限，已忽略")
        return None
    prefix, sep, payload = url.partition(";base64,")
    if not sep or not prefix.startswith("data:") or not payload:
        return None
    mime = prefix[len("data:") :]
    if not _MIME_PATTERN.fullmatch(mime):
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None
    if not raw or len(raw) > _MAX_DECODED_BYTES:
        return None
    return mime, hashlib.sha256(raw).hexdigest(), raw


def _iter_content_parts(message: CONTENT_LIST_TYPE_ITEM) -> list[Content] | None:
    """取出消息中 list 形式的内容；字符串内容 / ToolResult 返回 ``None``。"""
    if not isinstance(message, Message):
        return None
    content = message.content
    return list(content) if isinstance(content, list) else None


#  多模态二进制：写入


async def store_media(uni_id: str, raw: bytes, mime: str) -> str | None:
    """把图片二进制写入本地存储。

    :return: 成功时返回 ``media_id``（sha256 hex）；体积超限或内容为空时返回 ``None``
        （调用方应直接丢弃该图片，即"大图直接不接收"）。
    """
    if not raw:
        return None
    limit_kb = config_manager.config.context.max_image_kb
    if limit_kb > 0 and len(raw) > limit_kb * 1024:
        logger.debug(
            f"图片体积 {len(raw) / 1024:.1f}KB 超出上限 {limit_kb}KB，已丢弃该图片"
        )
        return None

    #  mime 会被拼回 ``data:<mime>;base64,``，因此不能透传不可信值
    mime = _sanitize_mime(mime)
    media_id = hashlib.sha256(raw).hexdigest()
    #  并发写入同一 media_id 会撞唯一约束：锁池只能串行化本进程，多 worker 共享
    #  同一个数据库时还要兜住 IntegrityError
    async with _lock_for(f"media:{media_id}"):
        async with get_session() as session:
            exists = await session.execute(
                select(ContextMedia.id).where(ContextMedia.media_id == media_id)
            )
            if exists.scalar_one_or_none() is None:
                session.add(
                    ContextMedia(
                        media_id=media_id,
                        uni_id=uni_id,
                        mime=mime,
                        size=len(raw),
                        data=raw,
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    #  另一个进程刚写入同一行：内容寻址下两者完全等价，直接复用
                    await session.rollback()
                    logger.debug(f"媒体 {media_id[:8]} 已由其它进程写入，复用已有记录")
    await _maybe_prune()
    return media_id


async def load_media_data_uri(media_id: str) -> str | None:
    """按 ``media_id`` 取回 ``data:<mime>;base64,<payload>``；不存在时返回 ``None``。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(ContextMedia.mime, ContextMedia.data).where(
                    ContextMedia.media_id == media_id
                )
            )
        ).one_or_none()
    if row is None:
        return None
    mime, data = row
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


#  读路径：占位符 -> base64


async def _resolve_part(part: Content) -> Content:
    if not isinstance(part, PlaceholderContent):
        return part
    url = await load_media_data_uri(part.media_id)
    if url is None:
        logger.debug(f"上下文媒体已不可用（{part.media_id[:8]}），降级为说明文本")
        return TextContent(text=f"[{part.kind} 已过期或不可用（{part.media_id[:8]}）]")
    #  登记：折叠时据此认出"这张图是本插件自己展开的"，从而在媒体行已被淘汰的
    #  情况下也能折回占位符
    _remember_expanded(part.media_id)
    return ImageContent(image_url=ImageUrl(url=url))


def _has_placeholder(parts: Iterable[Content]) -> bool:
    return any(isinstance(part, PlaceholderContent) for part in parts)


async def resolve_placeholders_in_messages(
    messages: Iterable[CONTENT_LIST_TYPE_ITEM],
) -> list[CONTENT_LIST_TYPE_ITEM]:
    """展开记忆中的占位符，返回**新的**消息列表（不修改传入对象）。

    调用方必须使用返回值。就地改写会把 base64 留在共享的记忆缓存里（见模块
    docstring 的设计约束），只含占位符以外的消息会原样复用，不做多余拷贝。
    """
    resolved: list[CONTENT_LIST_TYPE_ITEM] = []
    for message in messages:
        parts = _iter_content_parts(message)
        if (
            parts is None
            or not _has_placeholder(parts)
            or not isinstance(message, Message)
        ):
            resolved.append(message)
            continue
        expanded = message.model_copy()
        expanded.content = [await _resolve_part(part) for part in parts]
        resolved.append(expanded)
    return resolved


async def resolve_placeholders_in_content(content: USER_INPUT) -> USER_INPUT:
    """把当前轮用户输入中的占位符展开为 base64 图片内容。"""
    if content is None or isinstance(content, str):
        return content
    if not _has_placeholder(content):
        return content
    return [await _resolve_part(part) for part in content]


#  非多模态运行的占位符替身。
#  此时既不能展开成 base64（纯文本模型会直接报错），也不能把 PlaceholderContent
#  直接发给 API（Core 会把它序列化成 ``{"type": "placeholder", ...}``，同样报错），
#  更不能直接丢掉占位符（重新开启多模态后要能取回原图）。因此用一个带 media_id
#  的文本标记顶替，折叠时再由 :func:`_restore_omitted` 还原成占位符。
_OMITTED_PATTERN = re.compile(r"^\[图片已省略：([0-9a-f]{64}) ([^\]\s]+) (\d+)\]$")


def _omitted_text(part: PlaceholderContent) -> str:
    return f"[图片已省略：{part.media_id} {part.mime} {part.size}]"


def _parse_omitted(text: str) -> PlaceholderContent | None:
    match = _OMITTED_PATTERN.fullmatch(text)
    if match is None:
        return None
    return PlaceholderContent(
        media_id=match.group(1),
        kind="image",
        mime=match.group(2),
        size=int(match.group(3)),
    )


def has_placeholders(messages: Iterable[CONTENT_LIST_TYPE_ITEM]) -> bool:
    """消息列表中是否含有待展开 / 待折叠的占位符。"""
    for message in messages:
        parts = _iter_content_parts(message)
        if parts is not None and _has_placeholder(parts):
            return True
    return False


async def omit_placeholders_in_messages(
    messages: Iterable[CONTENT_LIST_TYPE_ITEM],
) -> list[CONTENT_LIST_TYPE_ITEM]:
    """把占位符换成文本标记，返回**新的**消息列表（不修改传入对象）。

    仅用于当前模型不支持多模态的运行：既不把 base64 送进请求，也不丢失占位符
    本身（写库前由 :func:`collapse_media_to_placeholders` 还原）。
    """
    omitted: list[CONTENT_LIST_TYPE_ITEM] = []
    for message in messages:
        parts = _iter_content_parts(message)
        if (
            parts is None
            or not _has_placeholder(parts)
            or not isinstance(message, Message)
        ):
            omitted.append(message)
            continue
        replaced = message.model_copy()
        replaced.content = [
            TextContent(text=_omitted_text(part))
            if isinstance(part, PlaceholderContent)
            else part
            for part in parts
        ]
        omitted.append(replaced)
    return omitted


#  写路径：base64 -> 占位符


def _restore_omitted(
    messages: Iterable[CONTENT_LIST_TYPE_ITEM], foldable: set[str]
) -> None:
    """就地把"已省略"文本标记还原成占位符。

    只还原 ``foldable``（库里确实存在）的 media_id：标记本身只是普通文本，任何
    用户都能照着格式发一条，不能让它变成"凭空引用某张图片"的入口。
    """
    for message in messages:
        parts = _iter_content_parts(message)
        if parts is None or not isinstance(message, Message):
            continue
        replaced: list[Content] = []
        changed = False
        for part in parts:
            restored = (
                _parse_omitted(part.text) if isinstance(part, TextContent) else None
            )
            if restored is not None and restored.media_id in foldable:
                replaced.append(restored)
                changed = True
                continue
            replaced.append(part)
        if changed:
            message.content = replaced


async def collapse_media_to_placeholders(
    messages: Iterable[CONTENT_LIST_TYPE_ITEM],
) -> None:
    """就地把 base64 的 ``ImageContent`` 折叠回占位符。

    判定只看内容：data URI 合法（严格校验 MIME 与 base64）即折叠。**不查询**
    :class:`ContextMedia` 是否存在——"行还在"并不是折叠的前提，媒体随时可能被 TTL
    淘汰，此时若不折叠，base64 就会被持久化进 ``memory_json``。

    例外：来源不明的 data URI（既不在库里、也不是本插件展开出来的）保持原样，
    避免静默丢弃；这类内容应由产生方先调用 :func:`store_media` 落库。

    顺带把非多模态运行留下的"已省略"文本标记还原成占位符。
    """
    messages = list(messages)
    #  按 url 缓存解码结果：同一张图在收集与折叠两个阶段只解码一次
    decoded: dict[str, tuple[str, str, bytes]] = {}
    omitted: set[str] = set()
    for message in messages:
        for part in _iter_content_parts(message) or ():
            if isinstance(part, ImageContent):
                url = part.image_url.url
                if url in decoded:
                    continue
                if (parsed := _decode_data_uri(url)) is not None:
                    decoded[url] = parsed
            elif (
                isinstance(part, TextContent)
                and (marker := _parse_omitted(part.text)) is not None
            ):
                omitted.add(marker.media_id)
    if not decoded and not omitted:
        return

    async with get_session() as session:
        rows = await session.execute(
            select(ContextMedia.media_id).where(
                ContextMedia.media_id.in_(
                    [item[1] for item in decoded.values()] + list(omitted)
                )
            )
        )
        foldable = set(rows.scalars().all())
    foldable |= _expanded_ids
    if not foldable:
        return

    #  先还原"已省略"标记（非多模态运行留下的文本替身），再折叠 base64
    _restore_omitted(messages, foldable)

    for message in messages:
        parts = _iter_content_parts(message)
        if parts is None or not isinstance(message, Message):
            continue
        replaced: list[Content] = []
        changed = False
        for part in parts:
            parsed = (
                decoded.get(part.image_url.url)
                if isinstance(part, ImageContent)
                else None
            )
            if parsed is not None and parsed[1] in foldable:
                replaced.append(
                    PlaceholderContent(
                        media_id=parsed[1],
                        kind="image",
                        mime=parsed[0],
                        size=len(parsed[2]),
                    )
                )
                changed = True
                continue
            replaced.append(part)
        if changed:
            message.content = replaced


#  上下文记录


async def append_context_record(
    *,
    uni_id: str,
    user_id: str,
    nickname: str,
    role: str,
    content: str,
) -> None:
    """静默记录一条群聊上下文（不进入 LLM 记忆）。

    ``content`` 需是已渲染好的文本（调用方用 ``utils.format.format_msg_xml``
    生成），本函数不再做格式处理。
    """
    if not config_manager.config.context.enable or not content.strip():
        return
    #  “计数 -> 淘汰最旧 -> 插入” 需要串行化，否则并发写入会多删或少删
    async with _lock_for(f"record:{uni_id}"):
        async with get_session() as session:
            session.add(
                ContextRecord(
                    uni_id=uni_id,
                    user_id=user_id,
                    nickname=nickname,
                    role=role,
                    content=content,
                )
            )
            #  触发 autoflush，让本次新增记录参与条数上限淘汰
            await _prune_records_for_session(
                session, uni_id, config_manager.config.context.max_records
            )
            await session.commit()
    await _maybe_prune()


async def read_context_records(
    uni_id: str, limit: int, keyword: str | None = None
) -> list[str]:
    """读取指定会话最近的上下文记录，按时间正序返回（已渲染好的文本）。"""
    cfg = config_manager.config.context
    #  ``read_context_limit`` 同时是默认值与上限，这里对任何调用者再夹一次
    limit = max(1, min(limit, cfg.read_context_limit))
    stmt = select(ContextRecord.content).where(ContextRecord.uni_id == uni_id)
    if keyword:
        stmt = stmt.where(ContextRecord.content.contains(keyword))
    stmt = stmt.order_by(
        ContextRecord.created_at.desc(), ContextRecord.id.desc()
    ).limit(limit)
    async with get_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return list(reversed(rows))


#  淘汰（条数上限 + TTL）


async def _prune_records_for_session(
    session: AsyncSession, uni_id: str, max_records: int
) -> None:
    if max_records <= 0:
        return
    stmt = (
        select(ContextRecord.id)
        .where(ContextRecord.uni_id == uni_id)
        .order_by(ContextRecord.created_at.desc(), ContextRecord.id.desc())
        .offset(max_records)
    )
    expired_ids = (await session.execute(stmt)).scalars().all()
    if expired_ids:
        await session.execute(
            delete(ContextRecord).where(ContextRecord.id.in_(expired_ids))
        )


async def prune_context_store() -> None:
    """按配置淘汰超期（TTL）的上下文记录与多模态二进制。"""
    cfg = config_manager.config.context
    now = datetime.now()
    async with get_session() as session:
        if cfg.record_ttl_hours > 0:
            deadline = now - timedelta(hours=cfg.record_ttl_hours)
            await session.execute(
                delete(ContextRecord).where(ContextRecord.created_at < deadline)
            )
        if cfg.media_ttl_hours > 0:
            deadline = now - timedelta(hours=cfg.media_ttl_hours)
            await session.execute(
                delete(ContextMedia).where(ContextMedia.created_at < deadline)
            )
        await session.commit()


async def _maybe_prune() -> None:
    """按 ``context.prune_interval_minutes`` 节流地触发一次淘汰。"""
    global _last_prune_at
    async with _prune_lock:
        now = time.monotonic()
        if now - _last_prune_at < _prune_interval_seconds():
            return
        _last_prune_at = now
        try:
            await prune_context_store()
        except Exception:
            logger.opt(exception=True).warning("上下文存储淘汰任务执行失败")
