"""插件状态判定。

把三个集合交叉起来，回答「这个插件现在到底处于什么状态」：

- **C** Configured —— ``pyproject.toml`` 里期望启用的（``[tool.nonebot]`` 与 ``[tool.amrita]``）
- **L** Loaded —— 本次启动实际加载成功的（``nonebot.get_loaded_plugins()``）
- **P** Present —— 环境里确实装着的（:mod:`amrita.utils.plugin_discovery` 的静态嗅探）

``plugins/`` 下的目录插件不经 ``pyproject.toml``，由目录扫描加载，存在即启用，
只参与 P 与 L 的判定；``src/plugins/`` 只被嗅探，不参与加载。

只看 C 和 L 分不出「包还没装」和「装了但没启用」；只看 P 又不知道有没有生效。
三者一起才能把「重启后启用」和「加载失败」也分开。

内置插件由加载器强制载入、不受 ``pyproject.toml`` 控制，一律判为 ``RUNNING``
并标注 ``builtin``，不参与其余状态。

.. warning::
   **无法从快照区分「被别的插件 require 进来的依赖」与「配置里被移除的插件」**——
   两者在运行时都表现为「已加载但不在配置里」。``nonebot.Plugin.parent_plugin``
   在本项目使用的 nonebot 版本里按模块名层级推导，对 ``nonebot_plugin_localstore``
   这类顶层模块始终为 ``None``，帮不上忙。

   实测 ``nonebot_plugin_localstore`` 与 ``nonebot_plugin_uniconf`` 就属于前者
   （被内置插件 require 进来），会被判为 ``PENDING_REMOVE``。上层若要避免误报，
   可自行传入豁免名单，或改为记录「曾配置过」的历史状态。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import nonebot

from .plugin_discovery import (
    DiscoveredPlugin,
    PluginKind,
    discover_plugins,
    is_builtin,
    is_indirect_dependency,
    local_plugin_dirs,
    protect_reason,
)
from .plugins import LOADED_PLUGIN_DIRS, get_load_failures
from .pyproject_io import read_plugin_list

__all__ = [
    "PluginEntry",
    "PluginSnapshot",
    "PluginState",
    "collect_configured",
    "collect_loaded",
    "collect_present",
    "resolve_states",
]

_DIST_KINDS: tuple[PluginKind, ...] = ("amrita_pkg", "nonebot_pkg")


class PluginState(str, Enum):
    """插件的六种状态。"""

    RUNNING = "running"
    """已配置且已加载，或是不受配置控制的内置插件、目录插件。"""

    PENDING_ENABLE = "pending_enable"
    """已配置（或已放进本地插件目录）但本次未加载，重启后应当生效。"""

    PENDING_REMOVE = "pending_remove"
    """本次已加载但配置里没有，重启后应当消失。"""

    LOAD_FAILED = "load_failed"
    """已配置却没能加载，通常是缺依赖或导入报错。"""

    DISABLED = "disabled"
    """包已装进环境，但没有写进配置，因此没有加载。"""

    NOT_INSTALLED = "not_installed"
    """既没配置也没安装。"""


@dataclass
class PluginEntry:
    """一个插件的完整状态描述。"""

    module_name: str
    name: str
    state: PluginState
    kind: PluginKind | None = None
    version: str | None = None
    project_link: str | None = None
    path: Path | None = None
    error: str | None = None
    is_dependency: bool = False
    """是否属于「被别的插件间接依赖」而被豁免的。"""
    protected_reason: str | None = None
    """非空表示不可禁用/卸载，内容为原因。"""

    def to_dict(self) -> dict[str, Any]:
        """转成可直接 JSON 序列化的字典。"""
        return {
            "module_name": self.module_name,
            "name": self.name,
            "state": self.state.value,
            "kind": self.kind,
            "version": self.version,
            "project_link": self.project_link,
            "path": str(self.path) if self.path is not None else None,
            "error": self.error,
            "is_dependency": self.is_dependency,
            "protected_reason": self.protected_reason,
        }


def collect_configured(path: Path | str | None = None) -> set[str]:
    """读取 ``pyproject.toml`` 中期望启用的插件模块名。"""
    return set(read_plugin_list("nonebot", path)) | set(
        read_plugin_list("amrita", path)
    )


def collect_loaded() -> set[str]:
    """本次启动实际加载的插件模块名（含内置插件）。"""
    return {plugin.module_name for plugin in nonebot.get_loaded_plugins()}


def collect_present(root: Path | str | None = None) -> dict[str, DiscoveredPlugin]:
    """环境里实际装着的插件，键为模块名。"""
    return {plugin.module_name: plugin for plugin in discover_plugins(root=root)}


@dataclass(frozen=True)
class PluginSnapshot:
    """某一时刻的三集合快照。"""

    configured: set[str]
    loaded: set[str]
    present: dict[str, DiscoveredPlugin]
    failures: dict[str, str]

    @classmethod
    def capture(
        cls, *, path: Path | str | None = None, root: Path | str | None = None
    ) -> PluginSnapshot:
        """采集当前快照。

        Args:
            path: ``pyproject.toml`` 路径；``None`` 时向上查找。
            root: 项目根，用于解析 ``plugins/`` 与 ``src/plugins/``；
                ``None`` 时由 ``pyproject.toml`` 的位置推断。

        Raises:
            PyprojectNotFoundError: 找不到 ``pyproject.toml``。
        """
        return cls(
            configured=collect_configured(path),
            loaded=collect_loaded(),
            present=collect_present(root),
            failures=get_load_failures(),
        )

    def is_local_dir(self, module_name: str) -> bool:
        """该模块是否来自加载器会扫描的本地插件目录。

        只认 :data:`~amrita.utils.plugins.LOADED_PLUGIN_DIRS`：``src/plugins/``
        下的插件即便放在那里也不会被加载，不能承诺「重启后启用」。
        """
        return local_plugin_dirs().get(module_name) in LOADED_PLUGIN_DIRS

    def state_of(self, module_name: str) -> PluginState:
        """判定单个模块的状态。"""
        if is_builtin(module_name):
            return PluginState.RUNNING
        configured = module_name in self.configured
        loaded = module_name in self.loaded
        if configured:
            if loaded:
                return PluginState.RUNNING
            if module_name in self.failures:
                return PluginState.LOAD_FAILED
            return PluginState.PENDING_ENABLE
        # 目录插件不写进 pyproject，放在目录里就是启用，不能按「配置里没有」判成待移除
        if self.is_local_dir(module_name):
            if module_name in self.failures:
                return PluginState.LOAD_FAILED
            return PluginState.RUNNING if loaded else PluginState.PENDING_ENABLE
        if loaded:
            # 被别的插件间接依赖的，重启后仍会被父插件拉起，不算「重启后移除」
            if is_indirect_dependency(module_name):
                return PluginState.RUNNING
            return PluginState.PENDING_REMOVE
        if module_name in self.present:
            return PluginState.DISABLED
        return PluginState.NOT_INSTALLED

    def entries(self, *, extra: Iterable[str] = ()) -> list[PluginEntry]:
        """汇总成条目列表。

        Args:
            extra: 额外要纳入的模块名，通常来自插件商店。这些名字若未安装，
                会以 :attr:`PluginState.NOT_INSTALLED` 出现。
        """
        names = set(self.configured) | set(self.loaded) | set(self.present)
        names.update(extra)

        result: list[PluginEntry] = []
        for module_name in sorted(names):
            found = self.present.get(module_name)
            kind: PluginKind | None = found.kind if found else None
            if kind is None and is_builtin(module_name):
                kind = "builtin"
            result.append(
                PluginEntry(
                    module_name=module_name,
                    name=found.name if found else module_name,
                    state=self.state_of(module_name),
                    kind=kind,
                    version=found.version if found else None,
                    project_link=(
                        found.name if found and found.kind in _DIST_KINDS else None
                    ),
                    path=found.path if found else None,
                    error=self.failures.get(module_name),
                    is_dependency=(
                        module_name not in self.configured
                        and module_name in self.loaded
                        and not is_builtin(module_name)
                        and is_indirect_dependency(module_name)
                    ),
                    protected_reason=protect_reason(module_name),
                )
            )
        return result


def resolve_states(
    *,
    path: Path | str | None = None,
    root: Path | str | None = None,
    extra: Iterable[str] = (),
) -> list[PluginEntry]:
    """采集快照并直接产出条目列表，等价于 ``PluginSnapshot.capture(...).entries(...)``。"""
    return PluginSnapshot.capture(path=path, root=root).entries(extra=extra)
