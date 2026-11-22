"""入站唯一转换点：event_preprocessor 阶段归一化并绑定上下文。"""

from __future__ import annotations

from nonebot.adapters import Bot, Event
from nonebot.message import event_preprocessor

from .shim import bind_envelope, envelope_from


@event_preprocessor
async def _bind_current_envelope(event: Event, bot: Bot) -> None:
    """转换失败（未注册的平台）时绑定 ``None``，不打断事件分发。

    不在这里复位：ContextVar 的生命周期与事件处理协程一致，
    与 Sense 的 ``current_uni_id`` 同一套用法。
    """
    bind_envelope(envelope_from(event, bot, strict=False))


__all__ = ["_bind_current_envelope"]
