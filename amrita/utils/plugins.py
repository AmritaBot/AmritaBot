# TODO: Amrita plugin system
import sys
from pathlib import Path
from venv import logger

import nonebot
import tomli


def add_module_dir(module_dir: str):
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)


def apply_alias():
    from ..plugins import chat

    sys.modules["nonebot_plugin_suggarchat"] = chat


def load_plugins():
    if "." not in sys.path:
        sys.path.insert(0, ".")
    nonebot.load_from_toml("pyproject.toml")

    for name in (Path(__file__).parent.parent / "plugins").iterdir():
        # 修改说明：为了Amrita项目的完整性，内置插件不会再允许被禁用。
        nonebot.logger.debug(f"Require built-in plugin {name.name}...")
        pl_name: str = f"amrita.plugins.{name.name}"
        try:
            nonebot.require(pl_name)
        except Exception:
            logger.debug("Try to load plugin manually...")
            nonebot.load_plugin(pl_name)
    nonebot.logger.debug("Appling Patches")
    apply_alias()
    nonebot.logger.info("Loading built-in plugins...")
    nonebot.logger.info("Loading plugins......")
    from amrita.models.pyproject import PyprojectFile

    with open("pyproject.toml", "rb") as f:
        meta = PyprojectFile.model_validate(tomli.load(f))

    for plugin in meta.tool.nonebot.plugins:
        nonebot.logger.debug(f"Loading NoneBot plugin {plugin}...")
        try:
            nonebot.require(plugin)
        except Exception as e:
            nonebot.logger.error(f"Failed to load plugin {plugin}: {e}")
    for plugin in meta.tool.amrita.plugins:
        nonebot.logger.debug(f"Loading Amrita plugin {plugin}...")
        try:
            nonebot.require(plugin)
        except Exception as e:
            nonebot.logger.error(f"Failed to load plugin {plugin}: {e}")
    nonebot.logger.info("Require local plugins......")
    nonebot.load_plugins("plugins")
