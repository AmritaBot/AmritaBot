from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher

from ..utils.app import CachedGroupDataRepository


async def enable(event: GroupMessageEvent, matcher: Matcher):
    """处理启用聊天功能的命令"""

    # 记录日志
    logger.debug(f"{event.group_id} enabled")

    # 获取并更新群组配置数据
    repo = CachedGroupDataRepository()
    group_config = await repo.get_group_config(event.group_id)
    group_config.enable = True
    await repo.update_group_config(group_config)

    await matcher.send("已启用聊天功能")
