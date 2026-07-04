from nonebot.plugin import PluginMetadata, require

require("nonebot_plugin_localstore")
require("nonebot_plugin_orm")
require("amrita.plugins.menu")
from . import command_manager, config, on_init
from .commands import lp_chat_group, lp_perm_group, lp_user, main
from .config import DataManager

__all__ = [
    "DataManager",
    "command_manager",
    "config",
    "lp_chat_group",
    "lp_perm_group",
    "lp_user",
    "main",
    "on_init",
]

__plugin_meta__ = PluginMetadata(
    name="Amrita 权限管理模块",
    description="Amrita内置的权限组件",
    usage="https://amrita.suggar.top/amrita/plugins/liteperm/",
    homepage="https://github.com/AmritaBot/Amrita",
    type="library",
    supported_adapters={"~onebot.v11"},
)
