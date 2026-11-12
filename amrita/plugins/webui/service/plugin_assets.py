"""插件前端产物的来源解析与 URL 生成。

外部插件的 UI 产物有两种来源，都只需声明一个名字，宿主负责拼 URL、
附加版本参数、检查可用性：

- **插件自带**（推荐，生产用）：插件把自己的产物目录随 Python 包分发，
  用 :func:`mount_plugin_assets` 注册。宿主把它挂到 ``/plugin-assets/<name>/``。
  产物在插件包内，宿主前端重建不会波及，pip 装上就有 UI。
- **静态目录**（开发便利）：放在 ``static/plugins/<name>/`` 下，直接声明
  ``module_dir=<name>`` 即可，不必写挂载代码。但该目录属于宿主构建产物，
  ``scripts/cleanup.sh`` 会清空它，因此不适合作为发布形态。

两种方式对插件作者是同一个参数（``module_dir``），差异只在宿主如何解析。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from .main import STATIC_PATH, app

__all__ = [
    "PLUGIN_ASSETS_ROOT",
    "list_mounted_assets",
    "mount_plugin_assets",
    "plugin_asset_url",
    "resolve_plugin_assets",
]

PLUGIN_ASSETS_ROOT = STATIC_PATH / "plugins"

# 产物入口文件名约定，插件侧构建套件默认输出这个名字
ENTRY_FILE = "index.js"

# 已挂载的插件自带产物：name -> 目录。挂载顺序即覆盖顺序
_MOUNTED: dict[str, Path] = {}


def _safe_name(name: str) -> str | None:
    """只接受单层名字，挡住 ``../`` 这类越界写法。"""
    cleaned = name.strip().strip("/")
    if not cleaned or "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        return None
    return cleaned


def mount_plugin_assets(name: str, directory: str | Path) -> str:
    """把插件自带的 UI 产物目录挂到 ``/plugin-assets/<name>/``。

    应在插件 import 期调用：SPA 的 catch-all 路由挂在 ``driver.on_startup``，
    晚于它挂载的静态目录会被抢先匹配。

    Args:
        name: 挂载名，也是 :func:`register_page` 里 ``module_dir`` 的值
        directory: 产物目录，通常是插件包内的 ``webui`` 子目录

    Returns:
        实际使用的挂载名

    Raises:
        ValueError: 名字不是单层目录名
        FileNotFoundError: 目录不存在或缺少入口文件
    """
    safe = _safe_name(name)
    if safe is None:
        raise ValueError(f"插件产物名只能是单层目录名：{name!r}")

    root = Path(directory).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"插件产物目录不存在：{root}")
    if not (root / ENTRY_FILE).is_file():
        raise FileNotFoundError(f"插件产物目录缺少入口文件 {ENTRY_FILE}：{root}")

    if safe in _MOUNTED:
        # 重复注册视为热重载后的覆盖，不重复 mount（StaticFiles 无法卸载）
        _MOUNTED[safe] = root
        return safe

    app.mount(
        f"/plugin-assets/{safe}",
        StaticFiles(directory=root),
        name=f"plugin-assets-{safe}",
    )
    _MOUNTED[safe] = root
    return safe


def list_mounted_assets() -> dict[str, str]:
    """已挂载的插件自带产物（名字 -> 目录字符串），供调试与诊断使用。"""
    return {name: str(path) for name, path in _MOUNTED.items()}


def _resolve_dir(name: str) -> tuple[Path, str] | None:
    """按优先顺序找出产物目录与其 URL 前缀。"""
    if mounted := _MOUNTED.get(name):
        return mounted, f"/plugin-assets/{name}"
    static_dir = PLUGIN_ASSETS_ROOT / name
    if static_dir.is_dir():
        return static_dir, f"/static/plugins/{name}"
    return None


def resolve_plugin_assets(module_dir: str) -> dict[str, object]:
    """解析插件产物，返回前端渲染所需的信息。

    Returns:
        含 ``module_dir`` / ``module_url`` / ``available`` / ``reason`` 的字典。
        产物不存在时 ``module_url`` 为 None，``reason`` 说明缺在哪。
    """
    name = _safe_name(module_dir)
    if name is None:
        return {
            "module_dir": module_dir,
            "module_url": None,
            "available": False,
            "reason": "module_dir 只能是单层目录名",
        }

    resolved = _resolve_dir(name)
    if resolved is None:
        return {
            "module_dir": name,
            "module_url": None,
            "available": False,
            "reason": (
                f"未找到插件产物 {name}：请在插件 import 期调用 "
                f"mount_plugin_assets({name!r}, <产物目录>)，"
                f"或把产物放到 static/plugins/{name}/"
            ),
        }

    root, prefix = resolved
    entry = root / ENTRY_FILE
    if not entry.is_file():
        return {
            "module_dir": name,
            "module_url": None,
            "available": False,
            "reason": f"插件产物目录缺少入口文件 {ENTRY_FILE}：{prefix}/{ENTRY_FILE}",
        }

    # mtime 做版本参数：import() 按 URL 缓存模块，插件改完重建后必须换 URL 才会生效
    mtime = int(entry.stat().st_mtime)
    return {
        "module_dir": name,
        "module_url": f"{prefix}/{ENTRY_FILE}?v={mtime}",
        "available": True,
        "reason": None,
    }


def plugin_asset_url(module_dir: str) -> str | None:
    """便捷入口：只要 URL（产物不可用时返回 None）。"""
    info = resolve_plugin_assets(module_dir)
    url = info.get("module_url")
    return url if isinstance(url, str) else None
