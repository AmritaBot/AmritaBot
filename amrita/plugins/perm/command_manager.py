"""LitePerm 命令注册器：基于 Alconna 封装 /lp 与点号子命令。"""

from __future__ import annotations

from typing import Any

from arclet.alconna import Alconna, Args, MultiVar
from nonebot.permission import Permission
from nonebot.typing import T_PermissionChecker, T_State
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.matcher import AlconnaMatcher


class _LPCommandGroup:
    """保持与原 CommandGroup 一致的注册入口，内部委托 on_alconna。"""

    def __init__(self, base: str, *, priority: int = 10, block: bool = True) -> None:
        self.base = base
        self.priority = priority
        self.block = block
        self.matchers: list[type[AlconnaMatcher]] = []

    def command(
        self,
        sub: str | tuple[str, ...],
        *,
        with_params: bool = False,
        permission: Permission | T_PermissionChecker | None = None,
        state: T_State | None = None,
        aliases: set[str] | None = None,
        priority: int | None = None,
        block: bool | None = None,
    ) -> type[AlconnaMatcher]:
        """注册 ``/lp`` 或 ``/lp.<sub...>`` 命令。

        Args:
            sub: 子命令名；空字符串或空元组表示主命令 ``/lp``
            with_params: 是否接收可变位置参数 ``params``
            permission: NoneBot 权限检查器
            state: 透传给 ``default_state``，供菜单插件读取 ``MatcherData``
            aliases: 额外命令别名
            priority: 覆盖默认优先级
            block: 覆盖默认阻断行为
        """
        parts = (sub,) if isinstance(sub, str) else sub
        non_empty = [part for part in parts if part]
        head = ".".join((self.base, *non_empty)) if non_empty else self.base
        alc = (
            Alconna(head, Args["params?", MultiVar(str)])
            if with_params
            else Alconna(head)
        )
        kwargs: dict[str, Any] = {
            "use_cmd_start": True,
            "priority": self.priority if priority is None else priority,
            "block": self.block if block is None else block,
        }
        if aliases:
            kwargs["aliases"] = aliases
        if permission is not None:
            kwargs["permission"] = permission
        if state is not None:
            kwargs["default_state"] = state
        matcher = on_alconna(alc, **kwargs)
        self.matchers.append(matcher)
        return matcher


command = _LPCommandGroup("lp", priority=10, block=True)
