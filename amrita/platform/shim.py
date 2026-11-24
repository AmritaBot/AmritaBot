"""手动转换入口与当前事件上下文。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from nonebot.adapters import Bot
from pydantic import BaseModel

from . import registry
from .dto import Actor, Envelope, Scope
from .identity import uni_id
from .ports import Sender

current_envelope_var: ContextVar[Envelope | None] = ContextVar(
    "amrita_current_envelope", default=None
)


class UnsupportedEvent(RuntimeError):
    """没有任何已注册实现能识别该事件。"""


def envelope_from(
    raw_event: BaseModel,
    bot: Bot | None = None,
    *,
    strict: bool = True,
) -> Envelope | None:
    """把平台原始事件归一化成 :class:`Envelope`。

    不做缓存：Envelope 持有 ``raw`` 的强引用，任何以事件对象为键的缓存
    都会被值反向钉住（弱引用键同样回收不掉），而一次转换只是字段搬运。
    """
    port = registry.resolve(raw_event, bot)
    if port is None:
        if strict:
            raise UnsupportedEvent(f"no platform port matched {type(raw_event)!r}")
        return None
    return port.to_envelope(raw_event, bot)


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
