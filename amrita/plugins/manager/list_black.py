"""列出黑名单命令：Alconna + EnvelopeNBDep + 公共转发/降级底座。"""

from __future__ import annotations

from arclet.alconna import Alconna
from nonebot.adapters import Bot
from nonebot.permission import Permission
from nonebot_plugin_alconna import on_alconna

from amrita.platform.di import EnvelopeNBDep
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.plugins.perm.API.rules import UserPermissionChecker
from amrita.utils.send import send_forward_msg

from .blacklist.black import bl_manager

black_list = on_alconna(
    Alconna("blacklist"),
    aliases={"黑名单"},
    use_cmd_start=True,
    default_state=MatcherData(
        name="列出黑名单",
        description="用于列出黑名单",
        usage="/blacklist",
        show_if="amrita.blacklist",
    ).model_dump(),
    permission=Permission(
        is_lp_admin, UserPermissionChecker("amrita.blacklist").checker()
    ),
)


@black_list.handle()
async def _(bot: Bot, env: EnvelopeNBDep):
    group_blacklist = await bl_manager.get_group_blacklist()
    private_blacklist = await bl_manager.get_private_blacklist()
    if not group_blacklist and not private_blacklist:
        await black_list.finish("📭 暂无黑名单")
    group_list_str = "".join(f"群：{k} 原因：{v}\n" for k, v in group_blacklist.items())
    private_blacklist_str = "".join(
        f"用户：{k} 原因：{v}\n" for k, v in private_blacklist.items()
    )
    parts: list[str] = []
    if group_list_str:
        parts.append("⚠️ 群黑名单列表：\n" + group_list_str)
    if private_blacklist_str:
        parts.append("⚠️ 用户黑名单列表：\n" + private_blacklist_str)
    await send_forward_msg(
        bot, env, "黑名单列表", env.self_id or str(bot.self_id), parts
    )
