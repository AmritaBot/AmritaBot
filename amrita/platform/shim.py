"""入站事件的转换入口（迁移期 shim）。

用法分两种，对应边界的两侧：

1. **系统外**（nonebot matcher / 插件入口）：``envelope_from(event, bot)``
   拿到归一化对象，再传给内部函数；
2. **系统内**：只接收 :class:`Envelope`，需要当前事件时读 ``current_envelope()``。

自动入口是 :mod:`amrita.platform.ingress`（``event_preprocessor``）；
这里只保留手动调用与上下文读写。

约定：转换失败（未注册的适配器）不抛异常打断消息流水线，
``envelope_from(..., strict=False)`` 返回 ``None``，由调用方决定降级方式。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from weakref import WeakKeyDictionary

from nonebot.adapters import Bot
from pydantic import BaseModel

from . import registry
from .dto import Actor, Envelope, Scope
from .identity import uni_id
from .ports import Sender

current_envelope_var: ContextVar[Envelope | None] = ContextVar(
    "amrita_current_envelope", default=None
)

# 同一事件会被多层反复转换，用弱引用缓存；不支持弱引用的实现退回有上限的 dict。
_cache: WeakKeyDictionary[BaseModel, Envelope] = WeakKeyDictionary()
_fallback_cache: dict[int, Envelope] = {}
_FALLBACK_CACHE_LIMIT = 256


class UnsupportedEvent(RuntimeError):
    """没有任何已注册实现能识别该事件。"""


def envelope_from(
    raw_event: BaseModel,
    bot: Bot | None = None,
    *,
    strict: bool = True,
) -> Envelope | None:
    """把平台原始事件归一化成 :class:`Envelope`。"""
    cached = _lookup(raw_event)
    if cached is not None:
        return cached
    port = registry.resolve(raw_event, bot)
    if port is None:
        if strict:
            raise UnsupportedEvent(f"no platform port matched {type(raw_event)!r}")
        return None
    envelope = port.to_envelope(raw_event, bot)
    _store(raw_event, envelope)
    return envelope


def sender_of(envelope: Envelope, bot: Bot) -> Sender:
    """按 Envelope 记录的 adapter 取发送实现，不靠平台名猜。"""
    port = None
    if envelope.adapter:
        port = registry.get_adapter(envelope.adapter)
    port = port or registry.get(envelope.scope.platform)
    return port.sender(bot, envelope.scope)


async def role_of(envelope: Envelope, bot: Bot) -> Actor:
    """按需补全角色：事件里没有（``role_known=False``）时向平台查询。

    每次调用都可能打一次平台 API，调用方负责自己的缓存策略；
    本层不做缓存，避免把"临时权限变更"钉死在内存里。
    """
    port = registry.get_adapter(envelope.adapter) if envelope.adapter else None
    port = port or registry.get(envelope.scope.platform)
    return await port.resolve_role(bot, envelope.scope, envelope.actor)


def uni_id_of(envelope: Envelope) -> str:
    """业务层主键，等价于 ``make_uni_id`` 的调用点。"""
    return uni_id(envelope.scope)


def current_envelope() -> Envelope | None:
    return current_envelope_var.get()


def bind_envelope(envelope: Envelope | None) -> Token[Envelope | None]:
    return current_envelope_var.set(envelope)


def reset_envelope(token: Token[Envelope | None]) -> None:
    current_envelope_var.reset(token)


@contextmanager
def envelope_scope(envelope: Envelope | None) -> Iterator[Envelope | None]:
    token = bind_envelope(envelope)
    try:
        yield envelope
    finally:
        reset_envelope(token)


def scope_of(envelope: Envelope) -> Scope:
    return envelope.scope


def actor_of(envelope: Envelope) -> Actor:
    return envelope.actor


def _lookup(raw_event: BaseModel) -> Envelope | None:
    try:
        return _cache.get(raw_event)
    except TypeError:
        return _fallback_cache.get(id(raw_event))


def _store(raw_event: BaseModel, envelope: Envelope) -> None:
    try:
        _cache[raw_event] = envelope
    except TypeError:
        if len(_fallback_cache) >= _FALLBACK_CACHE_LIMIT:
            _fallback_cache.clear()
        _fallback_cache[id(raw_event)] = envelope
