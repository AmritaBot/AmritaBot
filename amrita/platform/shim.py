"""事件归一化入口：把平台原始事件转成 :class:`Envelope`。

Envelope 只经由 matcher 的依赖注入（:data:`amrita.platform.EnvelopeNBDep`）
进入业务，本层不维护任何全局上下文，也不提供以事件为键的缓存。
"""

from __future__ import annotations

from nonebot.adapters import Bot
from pydantic import BaseModel

from . import registry
from .dto import Envelope


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
