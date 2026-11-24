from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Event

from amrita.utils.events import event_user_id

from ..config import DataManager
from .rules import (
    any_has_permission,
)

ENV_ADMINS = get_driver().config.superusers


async def is_lp_admin(event: Event) -> bool:
    """
    判断是否为管理员
    """
    user_id = event_user_id(event)
    if user_id is None:
        #  meta 事件没有发起者，不可能具备管理员身份
        return False

    return (
        user_id in ENV_ADMINS or await (any_has_permission("lp.admin"))(event)
    ) and DataManager().config.enable
