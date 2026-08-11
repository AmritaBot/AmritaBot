import nonebot
from nonebot.plugin import PluginMetadata, require

require("nonebot_plugin_uniconf")

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
    from .service import main, ws
    from .service.route import (
        api,
        auth,
        confedit,
        dbmeta,
        menu,
        permissions,
    )
    from .service.route import (
        config as route_config,
    )

    # 所有 API 路由注册完成后，最后注册 SPA catch-all
    main.mount_spa_fallback_on_startup()

    __all__ += [
        "api",
        "auth",
        "confedit",
        "dbmeta",
        "main",
        "menu",
        "permissions",
        "route_config",
        "ws",
    ]
