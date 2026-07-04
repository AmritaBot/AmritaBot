import nonebot
from nonebot.plugin import PluginMetadata, require

from .service.route import confedit

require("amrita.plugins.manager")
require("amrita.plugins.perm")

from .service import config
from .service.config import get_webui_config

__plugin_meta__ = PluginMetadata(
    name="Amrita WebUI",
    description="Amrita的原生WebUI",
    usage="打开bot 的webui页面",
    type="application",
    config=config.Config,
)

__all__ = ["config"]

webui_config = get_webui_config()
if webui_config.webui_enable:
    nonebot.logger.info("Mounting webui......")
    from .service import main
    from .service.route import (
        api,
        bot,
        confedit,
        dbmeta,
        index,
        user,
    )
    from .service.route import config as route_config

    __all__ += [
        "api",
        "bot",
        "confedit",
        "dbmeta",
        "index",
        "main",
        "route_config",
        "user",
    ]
