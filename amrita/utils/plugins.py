# TODO: Amrita plugin system
import sys
from pathlib import Path

import nonebot
import tomli

from .plugin_discovery import AMRITA_LOCAL_DIR
from .pyproject_io import PyprojectNotFoundError, find_pyproject

LOADED_PLUGIN_DIRS: tuple[str, ...] = (AMRITA_LOCAL_DIR,)
"""``load_plugins()`` 会扫描的本地插件目录。

``src/plugins/`` 只被 :mod:`amrita.utils.plugin_discovery` 嗅探，不参与加载，
因此不能按「放进目录即启用」处理。
"""

# 模块名 -> 失败原因。由 load_plugins() 填充，供 WebUI 呈现「加载失败」状态。
_LOAD_FAILURES: dict[str, str] = {}


def add_module_dir(module_dir: str):
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)


def apply_alias():
    from ..plugins import chat

    sys.modules["nonebot_plugin_suggarchat"] = chat


def record_load_failure(module_name: str, error: BaseException | str) -> None:
    """登记一次插件加载失败。

    ``pyproject.toml`` 里配了、但 ``require`` 抛异常的插件，光看配置和已加载
    集合分不出「重启后才会生效」还是「加载失败了」，靠这份名单补上。
    """
    _LOAD_FAILURES[module_name] = error if isinstance(error, str) else repr(error)


def get_load_failures() -> dict[str, str]:
    """返回本次启动以来的插件加载失败名单（模块名 → 错误摘要）。"""
    return dict(_LOAD_FAILURES)


def clear_load_failures() -> None:
    """清空失败名单。热重载与测试场景使用。"""
    _LOAD_FAILURES.clear()


def _require_plugin(module_name: str) -> None:
    """require 一个插件；失败时记日志并登记，不中断其余插件的加载。"""
    try:
        nonebot.require(module_name)
    except Exception as e:
        nonebot.logger.error(f"Failed to load plugin {module_name}: {e}")
        record_load_failure(module_name, e)


def load_plugins():
    if "." not in sys.path:
        sys.path.insert(0, ".")

    # 先定位项目根，避免依赖启动时的当前工作目录
    pyproject = find_pyproject()
    if pyproject is None:
        raise PyprojectNotFoundError("未找到 pyproject.toml，无法加载插件")

    nonebot.load_from_toml(str(pyproject))

    for name in sorted((Path(__file__).parent.parent / "plugins").iterdir()):
        # 修改说明：为了Amrita项目的完整性，内置插件不会再允许被禁用。
        nonebot.logger.debug(f"Require built-in plugin {name.name}...")
        pl_name: str = f"amrita.plugins.{name.name}"
        try:
            nonebot.require(pl_name)
        except Exception:
            nonebot.logger.debug("Try to load plugin manually...")
            nonebot.load_plugin(pl_name)
    nonebot.logger.debug("Appling Patches")
    apply_alias()
    nonebot.logger.info("Loading built-in plugins...")
    nonebot.logger.info("Loading plugins......")
    from amrita.models.pyproject import PyprojectFile

    with pyproject.open("rb") as f:
        meta = PyprojectFile.model_validate(tomli.load(f))

    for plugin in meta.tool.nonebot.plugins:
        nonebot.logger.debug(f"Loading NoneBot plugin {plugin}...")
        _require_plugin(plugin)
    for plugin in meta.tool.amrita.plugins:
        nonebot.logger.debug(f"Loading Amrita plugin {plugin}...")
        _require_plugin(plugin)
    nonebot.logger.info("Require local plugins......")
    nonebot.load_plugins(*LOADED_PLUGIN_DIRS)
