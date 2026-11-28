"""黑名单事件预处理：基于 Envelope 拦截黑名单群聊与用户。"""

from __future__ import annotations

from nonebot.adapters import Bot
from nonebot.exception import IgnoredException
from nonebot.matcher import Matcher
from nonebot.message import run_preprocessor

from amrita.platform.di import OptionalEnvelopeNBDep
from amrita.platform.dto import META
from amrita.platform.identity import uni_id, user_uni_id
from amrita.utils.admin import send_to_admin

from .blacklist.black import bl_manager
from .leave import leave_group


async def _is_group_blacklisted(group_id: str, group_uni_id: str) -> bool:
    if await bl_manager.is_group_black(group_id):
        return True
    return group_uni_id != group_id and await bl_manager.is_group_black(group_uni_id)


async def _is_user_blacklisted(user_id: str, user_uid: str) -> bool:
    if await bl_manager.is_private_black(user_id):
        return True
    return user_uid != user_id and await bl_manager.is_private_black(user_uid)


@run_preprocessor
async def message_preprocessor(matcher: Matcher, bot: Bot, env: OptionalEnvelopeNBDep):
    if env is None or env.kind == META:
        return
    if env.is_group and await _is_group_blacklisted(env.scope.id, uni_id(env.scope)):
        await send_to_admin(f"尝试退出黑名单群组{env.scope.id}.......")
        if env.scope.id.isdigit():
            await leave_group(bot, int(env.scope.id), adapter_hint=env.adapter or None)
        raise IgnoredException("群组黑名单")
    if env.actor.user_id and await _is_user_blacklisted(
        env.actor.user_id, user_uni_id(env.actor.platform, env.actor.user_id)
    ):
        raise IgnoredException("用户黑名单")
