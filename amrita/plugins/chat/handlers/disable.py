from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.matcher import Matcher

from ..utils.app import CachedGroupDataRepository


async def disable(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """处理禁用聊天功能的异步函数"""
    # 记录禁用操作日志
    logger.debug(f"{event.group_id} disabled")

    # 获取并更新群聊状态数据
    repo = CachedGroupDataRepository()
    group_config = await repo.get_group_config(event.group_id)
    group_config.enable = False
    await repo.update_group_config(group_config)

    await matcher.send("聊天功能已禁用")
