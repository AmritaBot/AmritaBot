from nonebot import get_driver, logger

from .deps import setup_core_runtime

driver = get_driver()


@driver.on_startup
async def onEnable():
    logger.debug("加载配置文件...")
    await setup_core_runtime()
    logger.debug("成功启动！")
