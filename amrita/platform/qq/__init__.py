"""QQ 平台适配器注册：OneBot 与 Milky 同属 platform=qq。"""

from __future__ import annotations

from ..registry import register
from .milky import MilkyPort
from .onebot import OneBotPort

register(OneBotPort())
register(MilkyPort())

__all__ = ["MilkyPort", "OneBotPort"]
