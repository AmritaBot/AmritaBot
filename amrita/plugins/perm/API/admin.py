from nonebot import get_driver
from nonebot.adapters import Event

from ..config import DataManager
from .rules import (
    any_has_permission,
)

ENV_ADMINS = get_driver().config.superusers


async def is_lp_admin(event: Event) -> bool:
    """
    判断是否为管理员
    """
    user_id = event.get_user_id()

    return (
        user_id in ENV_ADMINS or await (any_has_permission("lp.admin"))(event)
    ) and DataManager().config.enable
