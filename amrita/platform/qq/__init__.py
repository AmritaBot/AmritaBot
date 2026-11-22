"""QQ 平台的适配器注册。

onebot 与 milky 同属 ``platform="qq"``：业务层只认 platform，
记忆/权限主键由 :func:`amrita.platform.identity.uni_id` 推导，与适配器无关。

注册顺序有意义：onebot 的 ``match`` 只看模块名 + 具体基类，天然严格，
先注册可以避免把 onebot 事件误判给 milky 的宽松匹配。
"""

from __future__ import annotations

from ..registry import register
from .milky import MilkyPort
from .onebot import OneBotPort

register(OneBotPort())
register(MilkyPort())

__all__ = ["MilkyPort", "OneBotPort"]
