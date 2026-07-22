from nonebot.plugin import PluginMetadata, require

require("amrita.plugins.perm")
require("amrita.plugins.menu")
require("amrita.plugins.webui")
require("nonebot_plugin_orm")
require("nonebot_plugin_localstore")
require("nonebot_plugin_amrita")

from . import (
    config,
    hooks,
    matcher_manager,
    page,
    preprocess,
)

__all__ = [
    "config",
    "hooks",
    "matcher_manager",
    "page",
    "preprocess",
]

__plugin_meta__ = PluginMetadata(
    name="Amrita LLM聊天模块",
    description="Amrita内置的LLM聊天能力",
    usage="https://amrita.suggar.top/amrita/plugins/suggarchat/",
    homepage="https://github.com/AmritaBot/Amrita",
    type="application",
    supported_adapters={"~onebot.v11"},
)
