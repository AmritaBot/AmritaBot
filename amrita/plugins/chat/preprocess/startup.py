from nonebot import get_driver, logger

from ..skills import validate_skills
from .deps import setup_core_runtime

driver = get_driver()


@driver.on_startup
async def onEnable():
    logger.debug("加载配置文件...")
    await setup_core_runtime()
    # 尽力加载并校验 skills 目录（单个技能失败仅记录日志，不阻断启动）
    results = validate_skills()
    failed = [r.name for r in results if not r.ok]
    if failed:
        logger.warning(f"技能加载校验失败 {len(failed)} 个: {failed}")
    elif results:
        logger.info(f"技能加载校验完成: {len(results)} 个技能")
    logger.debug("成功启动！")
