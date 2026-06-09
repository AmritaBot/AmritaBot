from amrita_core import ToolsManager, init, load_amrita, set_config
from nonebot import get_driver, logger

from .config import config_manager
from .hook_manager import run_hooks

driver = get_driver()


@driver.on_startup
async def onEnable():
    logger.debug("加载配置文件...")
    config = await config_manager.safe_get_config()

    await run_hooks()
    logger.debug("正在加载AmritaCore...")
    core_config = config.core
    init()
    set_config(core_config)
    await load_amrita()
    ToolsManager().disable_tool(
        "processing_message"
    )  # This tool will be replaced by Amrita
    logger.debug("成功启动！")
