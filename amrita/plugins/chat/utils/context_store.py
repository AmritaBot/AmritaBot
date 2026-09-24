"""群聊上下文静默存储 / 多模态本地存储服务层。

本模块是"上下文静默存储"架构的唯一出入口，向上提供：

- :func:`append_context_record` —— 把一条未被触发的群消息静默落库（替代写入记忆）
- :func:`read_context_records` —— 供 ``read_context`` 工具按需读取
- :func:`store_media` —— 多模态二进制落库，返回占位符所需的 ``media_id``
- :func:`inject_image` —— 供钩子使用的图片注入 API（由本模块负责入库与落位）
- :func:`expand_media_in_messages` / :func:`expand_media_in_content`
  —— 读路径（**唯一**读图片二进制的入口）：占位符 -> 图片内容
- :func:`fold_media_in_messages` —— 写路径：图片内容 -> 占位符（**纯函数，无 IO**）

设计约束（重要）：**"记忆里只有占位符"必须是不变式，而不是"顺利的话"的副作用**。

1. 展开只作用于副本。展开函数返回新列表，调用方把它挂到 ``model_copy()`` 上。
   若就地改写共享的 ``CachedUserDataRepository._cached_memory``，一旦本次运行在
   ``COMMIT_MEMORY`` 之前中断（LLM 报错 / 超时 / 取消，它是工作流最后一个节点），
   缓存里残留的 base64 就会被后续任意"读缓存 + 写库"的命令（``/prompt set``、
   ``/session compact`` 等）持久化进 ``memory_json``。
2. 折叠是**纯哈希**。``media_id`` 就是二进制内容的 sha256，因此折叠只需重算哈希，
   不需要查询 :class:`ContextMedia`（媒体随时可能被 TTL 淘汰），也不需要任何
   进程内注册表。入库（:func:`store_media`）与折叠天然闭环。
3. 任何绕过 ``ChatMemoryBackend.commit_memory`` 的写库路径都必须经
   ``utils/data_access.py:update_memory``（它内部会先折叠）。

**不把结构化信息编码成文本。** 早期实现用 ``[图片已省略：<media_id> ...]`` 这样的
标记来在非多模态运行中暂存占位符，再由正则解析还原——这要求解析器去信任一段
用户可写的存储内容（用户照着格式发一条就能伪造标记、探测 ``media_id`` 是否存在），
是注入面的唯一来源。现在改为在**展开时**决定能否使用图片：不支持图片就换成固定
字面量 :data:`_NO_IMAGE_TEXT`，该分支不可逆（占位符在写回时已不存在）。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from amrita_core.hook.event import Event

__all__ = [
    "PlaceholderContent",
    "append_context_record",
    "expand_media_in_content",
    "expand_media_in_messages",
    "fold_media_in_messages",
    "has_placeholders",
    "inject_image",
    "load_media_data_uri",
    "placeholder_of",
    "prune_context_store",
    "read_context_records",
    "store_media",
]

#  MIME 白名单式校验：只允许 type/subtype 简单结构，防止不可信字符串拼进 data: URI 破坏结构
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
    #  并发写入同一 media_id 会撞唯一约束（锁池只串行化本进程，多 worker 共享库时需兜住）
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


#  读路径：占位符 -> 图片内容


#  不支持图片时占位符的替身：固定字面量，不含 id 与用户可控内容，故不可伪造、无法探测 media_id
_NO_IMAGE_TEXT = "[图片：当前模型不支持图片输入]"
#  占位符对应的二进制已被淘汰时的说明文本
_MEDIA_GONE_TEXT = "[图片已过期或不可用]"


def _has_placeholder(parts: Iterable[Content]) -> bool:
    return any(isinstance(part, PlaceholderContent) for part in parts)


def has_placeholders(messages: Iterable[CONTENT_LIST_TYPE_ITEM]) -> bool:
    """消息列表中是否含有待展开的占位符。"""
    for message in messages:
        parts = _iter_content_parts(message)
        if parts is not None and _has_placeholder(parts):
            return True
    return False


async def _expand_part(part: Content, *, multimodal: bool) -> Content:
    if not isinstance(part, PlaceholderContent):
        return part
    if not multimodal:
        return TextContent(text=_NO_IMAGE_TEXT)
    url = await load_media_data_uri(part.media_id)
    if url is None:
        logger.debug(f"上下文媒体已不可用（{part.media_id[:8]}），降级为说明文本")
        return TextContent(text=_MEDIA_GONE_TEXT)
    return ImageContent(image_url=ImageUrl(url=url))


async def expand_media_in_messages(
    messages: Iterable[CONTENT_LIST_TYPE_ITEM], *, multimodal: bool
) -> list[CONTENT_LIST_TYPE_ITEM]:
    """展开记忆中的占位符，返回**新的**消息列表（不修改传入对象）。

    这是本模块**唯一**读取图片二进制的入口，只在聊天触发阶段调用一次；
    ``ChatMemoryBackend.load_memory`` 不再碰图片。

    - ``multimodal=True``：占位符 -> ``data:<mime>;base64,...`` 的 ``ImageContent``；
      二进制已被淘汰时降级为 :data:`_MEDIA_GONE_TEXT`。
    - ``multimodal=False``：占位符 -> :data:`_NO_IMAGE_TEXT` 固定字面量。既不能
      展开成 base64（纯文本模型会直接报错），也不能把 ``PlaceholderContent``
      原样发出去（Core 会把它序列化成 ``{"type": "placeholder", ...}``，同样报错）。

    非多模态分支**不可逆**：写回时占位符已不存在，该会话历史里的图片引用就此消失
    （``ContextMedia`` 行本身仍在，直到 TTL）。这是刻意取舍，见模块 docstring。

    只含占位符以外的消息原样复用，不做多余拷贝。
    """
    expanded: list[CONTENT_LIST_TYPE_ITEM] = []
    for message in messages:
        parts = _iter_content_parts(message)
        if (
            parts is None
            or not _has_placeholder(parts)
            or not isinstance(message, Message)
        ):
            expanded.append(message)
            continue
        replaced = message.model_copy()
        replaced.content = [
            await _expand_part(part, multimodal=multimodal) for part in parts
        ]
        expanded.append(replaced)
    return expanded


async def expand_media_in_content(
    content: USER_INPUT, *, multimodal: bool
) -> USER_INPUT:
    """展开当前轮用户输入中的占位符（语义同 :func:`expand_media_in_messages`）。"""
    if content is None or isinstance(content, str):
        return content
    if not _has_placeholder(content):
        return content
    return [await _expand_part(part, multimodal=multimodal) for part in content]


#  写路径：图片内容 -> 占位符（纯函数）


def placeholder_of(url: str) -> PlaceholderContent | None:
    """把 ``data:<mime>;base64,<payload>`` 解析成占位符（纯函数，无 IO）。

    占位符的 ``media_id`` 就是二进制内容的 sha256，因此这个转换是自洽的：
    :func:`store_media` 用同一个哈希入库，两边天然对齐，无需查库。
    非 data URI / MIME 非法 / base64 非法 / 体积超限都返回 ``None``。
    """
    parsed = _decode_data_uri(url)
    if parsed is None:
        return None
    mime, media_id, raw = parsed
    return PlaceholderContent(media_id=media_id, kind="image", mime=mime, size=len(raw))


def fold_media_in_messages(messages: Iterable[CONTENT_LIST_TYPE_ITEM]) -> None:
    """就地把图片内容折回占位符。

    **纯函数：不读数据库、不查任何注册表。** ``media_id`` 是内容哈希，重算即可，
    所以媒体是否已被 TTL 淘汰都不影响正确性；入库（:func:`store_media`）与折叠
    经由同一个哈希闭环。

    认不出来的内容（非 data URI / 解码失败 / 超限）原样保留，不静默丢弃。
    同一张图只解析一次（按 url 缓存结果）。
    """
    messages = list(messages)
    parsed: dict[str, PlaceholderContent] = {}
    for message in messages:
        for part in _iter_content_parts(message) or ():
            url = part.image_url.url if isinstance(part, ImageContent) else None
            if url is None or url in parsed:
                continue
            if (placeholder := placeholder_of(url)) is not None:
                parsed[url] = placeholder
    if not parsed:
        return

    for message in messages:
        parts = _iter_content_parts(message)
        if parts is None or not isinstance(message, Message):
            continue
        replaced: list[Content] = []
        changed = False
        for part in parts:
            placeholder = (
                parsed.get(part.image_url.url)
                if isinstance(part, ImageContent)
                else None
            )
            if placeholder is not None:
                replaced.append(placeholder)
                changed = True
                continue
            replaced.append(part)
        if changed:
            message.content = replaced


#  钩子图片注入


async def inject_image(
    event: Event, raw: bytes, mime: str, *, multimodal: bool
) -> bool:
    """供钩子使用的图片注入 API：由框架负责入库与落位。

    调用方只需提供二进制与 MIME，不需要自己算哈希、建占位符或管理生命周期：
    先经 :func:`store_media` 落库（体积 / 空内容由它统一拒绝），再按本次运行的
    多模态能力追加到 ``event.original_context.end_messages``。图片属于"附加内容"，
    不插进历史，以免打乱已有消息顺序。

    :return: 注入成功返回 ``True``；``store_media`` 拒绝（体积超限 / 内容为空）
        时返回 ``False``。
    """
    chat_object = getattr(event, "chat_object", None)
    uni_id = getattr(chat_object, "session_id", "") or ""
    media_id = await store_media(uni_id=uni_id, raw=raw, mime=mime)
    if media_id is None:
        return False
    placeholder = PlaceholderContent(
        media_id=media_id, kind="image", mime=_sanitize_mime(mime), size=len(raw)
    )
    event.original_context.end_messages.append(
        Message(
            role="user",
            content=[await _expand_part(placeholder, multimodal=multimodal)],
        )
    )
    return True


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
