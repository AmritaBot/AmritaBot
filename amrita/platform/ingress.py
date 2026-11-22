"""入站唯一转换点：在 nonebot 的事件预处理阶段把事件归一化并绑定。

分工（见 REFACTOR.md 第 16 节）：

* **agent 系统外**（nonebot matcher、插件入口）：拿到的是 nonebot 事件，
  通过这个预处理钩子或手动调用 :func:`envelope_from` 换得归一化对象；
* **agent 系统内**：只允许出现 :class:`Envelope`，不允许出现 nonebot 事件类型，
  也不允许走 Sense 的事件管线做二次转换。

放在 ``event_preprocessor`` 而不是各插件入口，是为了保证一次事件只转换一次，
并且早于所有 matcher / Sense 管线执行。
"""

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
