"""静态插件嗅探。

与运行时加载状态无关：这里回答的是「环境里装了哪些插件、它们放在哪」，
不关心它们有没有被成功加载。

四类来源沿用 ambot 的约定：

- ``amrita_plugin_`` 开头的发行包 —— pip 安装的 Amrita 插件
- ``nonebot_plugin_`` 开头的发行包 —— pip 安装的 NoneBot 插件
- ``plugins/`` 下的子目录 —— 本地 Amrita 插件
- ``src/plugins/`` 下的子目录 —— 本地 NoneBot 插件

.. note::
   发行包名要按 PEP 503 归一化后再比对前缀。PyPI 上的包名用连字符
   （``nonebot-plugin-orm``），直接拿 ``nonebot_plugin_`` 去 ``startswith``
   一个都匹配不到。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.metadata import distributions, packages_distributions
from pathlib import Path
from typing import Any, Literal

from packaging.requirements import Requirement

from .pyproject_io import find_pyproject

__all__ = [
    "AMRITA_DIST_PREFIX",
    "AMRITA_LOCAL_DIR",
    "NONEBOT_DIST_PREFIX",
    "NONEBOT_LOCAL_DIR",
    "DiscoveredPlugin",
    "PluginKind",
    "builtin_plugins_dir",
    "discover_plugins",
    "invalidate_reverse_dependencies",
    "is_builtin",
    "is_indirect_dependency",
    "iter_dir_plugins",
    "iter_dist_plugins",
    "local_plugin_dirs",
    "module_distributions",
    "normalize_dist_name",
    "protect_reason",
    "required_by_others",
    "reverse_dependencies",
    "runtime_required_modules",
]

PluginKind = Literal["builtin", "amrita_pkg", "nonebot_pkg", "local"]

AMRITA_DIST_PREFIX = "amrita_plugin_"
NONEBOT_DIST_PREFIX = "nonebot_plugin_"

AMRITA_LOCAL_DIR = "plugins"
"""本地 Amrita 插件目录（相对项目根）；``load_plugins()`` 会扫描它。"""

NONEBOT_LOCAL_DIR = "src/plugins"
"""本地 NoneBot 插件目录（相对项目根）；目前只被嗅探，不参与加载。"""

_BUILTIN_NAMESPACE = "amrita.plugins."

_SEPARATORS = re.compile(r"[-_.]+")


def normalize_dist_name(name: str) -> str:
    """按 PEP 503 归一化发行包名：``-`` / ``_`` / ``.`` 合并为 ``-`` 并小写。"""
    return _SEPARATORS.sub("-", name).lower()


def _to_module_name(dist_name: str) -> str:
    """发行包名 → 顶层模块名的兜底换算。"""
    return _SEPARATORS.sub("_", dist_name).lower()


@dataclass(frozen=True)
class DiscoveredPlugin:
    """一个被嗅探到的插件。"""

    name: str
    """发行包名，或本地插件的目录名。"""

    module_name: str
    """可导入的模块名；本地目录插件只能取目录名。"""

    kind: PluginKind
    version: str | None = None
    path: Path | None = None
    """本地插件的目录路径；pip 插件为 ``None``。"""


def iter_dist_plugins(prefix: str) -> list[tuple[str, str]]:
    """列出环境中以 ``prefix`` 开头的已安装发行包。

    ``prefix`` 与包名都会先按 :func:`normalize_dist_name` 归一化再比对，
    因此 ``nonebot_plugin_`` 与 ``nonebot-plugin-`` 等价。

    Returns:
        ``[(发行包名, 版本), ...]``，按包名排序。
    """
    wanted = normalize_dist_name(prefix)
    found: list[tuple[str, str]] = []
    for dist in distributions():
        metadata = dist.metadata
        name = metadata["Name"] if metadata is not None else None
        if name and normalize_dist_name(name).startswith(wanted):
            found.append((name, dist.version or ""))
    return sorted(found)


def iter_dir_plugins(dir_path: Path | str) -> list[str]:
    """列出目录下的插件子目录，忽略 ``_`` 与 ``.`` 开头的项。

    Args:
        dir_path: 插件目录，例如项目根下的 ``plugins``。

    Returns:
        按名排序的子目录名；目录不存在时返回空列表。
    """
    path = Path(dir_path)
    if not path.is_dir():
        return []
    return sorted(
        entry.name
        for entry in path.iterdir()
        if entry.is_dir() and not entry.name.startswith(("_", "."))
    )


def builtin_plugins_dir() -> Path:
    """内置插件目录 ``amrita/plugins``。

    直接由本文件位置推导，避免 import ``amrita`` 而触发整套框架初始化。
    """
    return Path(__file__).resolve().parent.parent / "plugins"


def is_builtin(module_name: str, plugins_dir: Path | str | None = None) -> bool:
    """判断 ``module_name`` 是否指向 Amrita 的内置插件。

    内置插件由加载器强制载入、不受 ``pyproject.toml`` 控制，
    因此必须排除在插件状态机之外。

    Args:
        module_name: 形如 ``amrita.plugins.chat`` 的模块名。
        plugins_dir: 内置插件目录；``None`` 时用 :func:`builtin_plugins_dir`。

    Returns:
        命名空间匹配**且**磁盘上确有同名子目录时为 ``True``。
        只判前缀会误伤同名的第三方包，所以一定要落到目录上。
    """
    if not module_name.startswith(_BUILTIN_NAMESPACE):
        return False
    top = module_name[len(_BUILTIN_NAMESPACE) :].split(".", 1)[0]
    if not top:
        return False
    base = Path(plugins_dir) if plugins_dir is not None else builtin_plugins_dir()
    return (base / top).is_dir()


def _dist_module_map() -> dict[str, str]:
    """``归一化发行包名`` → 顶层模块名。"""
    mapping: dict[str, str] = {}
    for module, dists in packages_distributions().items():
        for dist in dists:
            key = normalize_dist_name(dist)
            known = mapping.get(key)
            if known is None or len(module) < len(known):
                mapping[key] = module
    return mapping


def _project_root(root: Path | str | None = None) -> Path:
    """项目根：显式传入优先，否则由 ``pyproject.toml`` 位置推断，再退回当前目录。"""
    if root is not None:
        return Path(root).resolve()
    pyproject = find_pyproject()
    return pyproject.parent if pyproject is not None else Path.cwd().resolve()


def discover_plugins(
    *,
    root: Path | str | None = None,
    amrita_dir: str = AMRITA_LOCAL_DIR,
    nonebot_dir: str = NONEBOT_LOCAL_DIR,
) -> list[DiscoveredPlugin]:
    """汇总四类来源的插件。

    Args:
        root: 项目根目录。``None`` 时由 :func:`~amrita.utils.pyproject_io.find_pyproject`
            向上定位；再找不到就退回当前工作目录。
        amrita_dir: 本地 Amrita 插件目录，相对 ``root``。
        nonebot_dir: 本地 NoneBot 插件目录，相对 ``root``。

    Returns:
        按 ``(kind, 名字小写)`` 排序的插件列表。

    .. note::
       本地目录插件的 ``module_name`` 只能取目录名——它们由
       ``nonebot.load_plugins`` 按目录导入，不经 ``pyproject.toml`` 寻址。
    """
    base = _project_root(root)

    dist_map = _dist_module_map()
    plugins: list[DiscoveredPlugin] = []

    dist_sources: tuple[tuple[str, PluginKind], ...] = (
        (AMRITA_DIST_PREFIX, "amrita_pkg"),
        (NONEBOT_DIST_PREFIX, "nonebot_pkg"),
    )
    for prefix, kind in dist_sources:
        for name, version in iter_dist_plugins(prefix):
            normalized = normalize_dist_name(name)
            plugins.append(
                DiscoveredPlugin(
                    name=name,
                    module_name=dist_map.get(normalized, _to_module_name(name)),
                    kind=kind,
                    version=version,
                )
            )

    for sub in (amrita_dir, nonebot_dir):
        directory = base / sub
        plugins.extend(
            DiscoveredPlugin(
                name=name,
                module_name=name,
                kind="local",
                path=directory / name,
            )
            for name in iter_dir_plugins(directory)
        )

    plugins.sort(key=lambda plugin: (plugin.kind, plugin.name.lower()))
    return plugins


_LOCAL_DIR_CACHE: dict[str, str] | None = None
_REVERSE_CACHE: dict[str, frozenset[str]] | None = None
_MODULE_DIST_CACHE: dict[str, str] | None = None
_RUNTIME_REQUIRED_CACHE: frozenset[str] | None = None

#: 匹配插件源码里的 require("xxx") 调用
_REQUIRE_PATTERN = re.compile(r"""require\(\s*["\']([^"\']+)["\']""")


def _marker_allows_default(marker: Any) -> bool:
    """依赖标记在「未启用任何 extra」时是否成立。"""
    try:
        return bool(marker.evaluate({"extra": ""}))
    except Exception:
        return True


def reverse_dependencies(*, refresh: bool = False) -> dict[str, frozenset[str]]:
    """``归一化发行包名`` → 依赖它的发行包名集合。

    扫全部已安装发行包的 ``Requires-Dist``；带 extra 标记的依赖按「未启用
    extra」求值，只统计无条件依赖。

    结果会缓存——实测扫一遍 162 个发行包约 290 ms，不该每次请求都跑。
    安装或卸载成功后调用 :func:`invalidate_reverse_dependencies` 重建。
    """
    global _REVERSE_CACHE
    if _REVERSE_CACHE is not None and not refresh:
        return _REVERSE_CACHE

    reverse: dict[str, set[str]] = {}
    for dist in distributions():
        metadata = dist.metadata
        name = metadata["Name"] if metadata is not None else None
        if not name:
            continue
        owner = normalize_dist_name(name)
        for raw in dist.requires or []:
            try:
                requirement = Requirement(raw)
            except Exception:
                continue
            if requirement.marker is not None and not _marker_allows_default(
                requirement.marker
            ):
                continue
            reverse.setdefault(normalize_dist_name(requirement.name), set()).add(owner)

    _REVERSE_CACHE = {key: frozenset(value) for key, value in reverse.items()}
    return _REVERSE_CACHE


def module_distributions(*, refresh: bool = False) -> dict[str, str]:
    """顶层模块名 → 提供它的发行包名（归一化）。"""
    global _MODULE_DIST_CACHE
    if _MODULE_DIST_CACHE is not None and not refresh:
        return _MODULE_DIST_CACHE

    mapping: dict[str, str] = {}

    # 兜底：由发行包名推模块名，packages_distributions() 会漏掉没有 top_level.txt 的包
    for dist in distributions():
        metadata = dist.metadata
        name = metadata["Name"] if metadata is not None else None
        if name:
            mapping.setdefault(_to_module_name(name), normalize_dist_name(name))

    # packages_distributions() 的结果更权威，覆盖兜底值
    for module, dists in packages_distributions().items():
        for dist in dists:
            key = normalize_dist_name(dist)
            known = mapping.get(module)
            if known is None or len(key) < len(known):
                mapping[module] = key

    _MODULE_DIST_CACHE = mapping
    return _MODULE_DIST_CACHE


def local_plugin_dirs(*, refresh: bool = False) -> dict[str, str]:
    """``模块名`` → 本地插件目录（相对项目根）。

    只扫目录，不做发行包嗅探，供 :func:`protect_reason` 这类逐条调用的
    场景使用。同名目录同时存在时以 ``plugins/`` 为准。
    """
    global _LOCAL_DIR_CACHE
    if _LOCAL_DIR_CACHE is None or refresh:
        base = _project_root()
        found: dict[str, str] = {}
        for sub in (NONEBOT_LOCAL_DIR, AMRITA_LOCAL_DIR):
            for name in iter_dir_plugins(base / sub):
                found[name] = sub
        _LOCAL_DIR_CACHE = found
    return _LOCAL_DIR_CACHE


def invalidate_reverse_dependencies() -> None:
    """丢弃依赖与目录扫描的缓存。安装、卸载或 ``uv sync`` 之后调用。"""
    global _REVERSE_CACHE, _MODULE_DIST_CACHE, _RUNTIME_REQUIRED_CACHE
    global _LOCAL_DIR_CACHE
    _REVERSE_CACHE = None
    _MODULE_DIST_CACHE = None
    _RUNTIME_REQUIRED_CACHE = None
    _LOCAL_DIR_CACHE = None


def dependents(module_name: str) -> tuple[str, ...]:
    """依赖该模块所在发行包的那些发行包名（归一化、已排序）。

    返回空元组表示没人声明依赖它。
    """
    top = module_name.split(".", 1)[0]
    dist = module_distributions().get(top)
    if dist is None:
        return ()
    return tuple(sorted(reverse_dependencies().get(dist, ())))


def required_by_others(module_name: str) -> bool:
    """该模块是否被「别人」需要——内置插件 require 它，或宿主项目以外的发行包依赖它。

    宿主项目自己声明依赖只说明「这个插件装在这个项目里」（``uv add`` 会把它写进
    ``[project.dependencies]``），不算被别人需要，必须排除。
    """
    if module_name in runtime_required_modules():
        return True
    host = host_distribution()
    return any(name != host for name in dependents(module_name))


def is_indirect_dependency(module_name: str) -> bool:
    """该模块是否属于「被别的插件间接依赖」，因而豁免 ``PENDING_REMOVE``。

    判据与 :func:`protect_reason` 一致：内置插件的 ``require``，或宿主项目以外
    发行包的依赖。

    宿主项目自身的依赖声明不算——否则任何「装过、当前进程里还加载着、但已经从
    配置里删掉」的插件都会被豁免成 ``RUNNING``，禁用看起来毫无效果，直到下次
    重启才现形。
    """
    return required_by_others(module_name)


def host_distribution() -> str | None:
    """宿主项目自身的发行包名（归一化）。

    由本文件的包目录名推出——``amrita/utils/plugin_discovery.py`` 的顶层包就是
    ``amrita``。

    用途是把它从「谁依赖我」里排除：``uv add`` 会把每个装进来的插件写进项目
    自身的 dependencies，于是**每个**已安装插件的反向依赖里都有宿主项目。那
    只说明「它装在这个项目里」，不代表别的插件需要它。
    """
    package = Path(__file__).resolve().parent.parent.name
    return module_distributions().get(package)


def runtime_required_modules(*, refresh: bool = False) -> frozenset[str]:
    """内置插件源码里 ``require("...")`` 声明的模块名集合。

    这是最贴近运行时真实依赖关系的一手证据：发行包的 ``Requires-Dist`` 只描述
    包与包的关系，而插件之间是靠 ``require()`` 拉起来的。
    """
    global _RUNTIME_REQUIRED_CACHE
    if _RUNTIME_REQUIRED_CACHE is not None and not refresh:
        return _RUNTIME_REQUIRED_CACHE

    found: set[str] = set()
    root = builtin_plugins_dir()
    if root.is_dir():
        for path in root.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found.update(_REQUIRE_PATTERN.findall(text))
    _RUNTIME_REQUIRED_CACHE = frozenset(found)
    return _RUNTIME_REQUIRED_CACHE


def protect_reason(module_name: str) -> str | None:
    """该插件是否受保护（不可禁用 / 卸载）；返回原因，``None`` 表示可操作。

    与 :func:`is_indirect_dependency` 的豁免是两件事：豁免决定状态怎么显示，
    保护决定能不能操作。判据有四条：

    1. 内置插件——加载器强制载入，本就不受配置控制
    2. 被内置插件源码 ``require`` 的——禁用会让启动直接失败
    3. 被宿主项目**以外**的发行包声明为依赖的
    4. 本地目录插件——启用与否由目录本身决定，改配置不起作用
    """
    if is_builtin(module_name):
        return "内置插件不可禁用"
    if module_name in runtime_required_modules():
        return "被 Amrita 内置插件 require，禁用会导致启动失败"
    if (sub := local_plugin_dirs().get(module_name)) is not None:
        return f"本地目录插件由 {sub}/ 决定启用，禁用请移除该目录"
    host = host_distribution()
    others = [name for name in dependents(module_name) if name != host]
    if others:
        return f"被 {', '.join(others)} 依赖，禁用会连带破坏它们"
    return None
