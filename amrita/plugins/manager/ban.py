"""封禁群聊与用户命令。"""

from __future__ import annotations

from arclet.alconna import Alconna, Args, MultiVar
from nonebot_plugin_alconna import Match, on_alconna

from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin

from .blacklist.black import bl_manager

ban_group = on_alconna(
    Alconna("ban.group", Args["target?", str], Args["reason?", MultiVar(str)]),
    use_cmd_start=True,
    permission=is_lp_admin,
    default_state=MatcherData(
        name="封禁群",
        usage="/ban.group",
        description="封禁群聊",
        show_if="lp.admin",
    ).model_dump(),
)
ban_user = on_alconna(
    Alconna("ban.user", Args["target?", str], Args["reason?", MultiVar(str)]),
    use_cmd_start=True,
    permission=is_lp_admin,
    default_state=MatcherData(
        name="封禁用户",
        description="用于封禁用户",
        usage="/ban.user <user-id> [原因]",
        show_if="lp.admin",
    ).model_dump(),
)


@ban_group.handle()
async def _(target: Match[str], reason: Match[tuple[str, ...]]):
    group_id = target.result.strip() if target.available else ""
    if not group_id:
        await ban_group.finish("❌ 请提供封禁的群ID！")
    if await bl_manager.is_group_black(group_id):
        await ban_group.finish("❌ 该群已被封禁！")
    reason_text = " ".join(reason.result).strip() if reason.available else ""
    if reason_text:
        await bl_manager.group_append(group_id, reason_text)
    else:
        await bl_manager.group_append(group_id)
    await ban_group.finish(f"✅ 封禁群{group_id}成功！")


@ban_user.handle()
async def ban_user_handle(target: Match[str], reason: Match[tuple[str, ...]]):
    user_id = target.result.strip() if target.available else ""
    if not user_id:
        await ban_user.finish("❌ 请提供要封禁的用户ID！")
    if await bl_manager.is_private_black(user_id):
        await ban_user.finish("❌ 该用户已被封禁！")
    reason_text = " ".join(reason.result).strip() if reason.available else ""
    if reason_text:
        await bl_manager.private_append(user_id, reason_text)
    else:
        await bl_manager.private_append(user_id)
    await ban_user.finish(f"✅ 封禁用户{user_id}成功！")
