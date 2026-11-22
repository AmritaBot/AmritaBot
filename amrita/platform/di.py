"""依赖注入入口：仅面向 agent 系统之外的 nonebot matcher。

内部分工（见 REFACTOR.md 第 16 节）：

* agent 系统外：``@on_command`` / ``@on_message`` 这类 nonebot matcher，
  用 :data:`EnvelopeNBDep` 声明参数，或手动 ``envelope_from(event, bot)``；
* agent 系统内：只有 :class:`Envelope` 这一种数据类型，**不走 DI**，
  也不出现 nonebot 事件类型；需要时从上下文取 :func:`current_envelope`。

刻意不提供 AmritaSense 版的 ``Depends``：Sense 属于 agent 内部管线，
在内部再做一次"事件 → Envelope"的转换等于把边界向内挪，两套转换迟早不一致。
"""

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
