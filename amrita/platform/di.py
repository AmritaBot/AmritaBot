"""依赖注入入口：仅面向 nonebot 原生 matcher。"""

from __future__ import annotations

from typing import Annotated

from nonebot.adapters import Bot, Event
from nonebot.params import Depends as NoneBotDepends

from .dto import Envelope
from .shim import UnsupportedEvent, envelope_from


async def provide_envelope(event: Event, bot: Bot | None = None) -> Envelope:
    """把当前事件转换成 Envelope；无法识别时明确失败，而不是注入 ``None``。"""
    envelope = envelope_from(event, bot, strict=False)
    if envelope is None:
        raise UnsupportedEvent(f"no platform port matched {type(event)!r}")
    return envelope


# 仅用于 nonebot 原生 matcher
EnvelopeNBDep = Annotated[Envelope, NoneBotDepends(provide_envelope)]

__all__ = ["EnvelopeNBDep", "provide_envelope"]
