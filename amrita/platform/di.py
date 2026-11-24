"""依赖注入入口：信封只通过 matcher 的依赖注入进入业务。

用法（Alconna 的参数与信封依赖并存，由 nonebot 的 DI 一起解析）::

    from amrita.platform import EnvelopeNBDep

    @on_alconna(...)
    async def handler(args: SomeAlconnaArgs, env: EnvelopeNBDep) -> None:
        ...

不需要事件预处理器去"预先绑定上下文"：那样每个事件（含心跳、生命周期）都会被
归一化一遍，而真正要用信封的只有声明了依赖的 matcher。
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
