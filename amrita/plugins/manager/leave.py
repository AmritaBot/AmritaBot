"""退出群聊命令（alconna 迁移试点）。

这个命令是迁移样板：参数解析交给 alconna，环境信息来自 platform 层的
``Envelope``，两者都不依赖具体适配器事件。

选它做试点的原因：单命令、单文件、无内部调用链，改坏了只影响一条命令。
"""

from __future__ import annotations

from arclet.alconna import Alconna, Args
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna import Match, on_alconna

from amrita.platform.di import EnvelopeNBDep
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.admin import send_to_admin

set_leave = on_alconna(
    Alconna("set_leave", Args["target?", str]),
    permission=is_lp_admin,
    default_state=MatcherData(
        name="退出指定群聊",
        description="用于退出群聊",
        usage="/set_leave [<group-id>|--this]",
        show_if="lp.admin",
    ).model_dump(),
)


async def is_group_owner(bot: Bot, group_id: int) -> bool:
    """检测 Bot 是否为指定群的群主（群主无法主动退群）"""
    try:
        member = await bot.get_group_member_info(
            group_id=group_id, user_id=int(bot.self_id)
        )
    except Exception:
        return False
    return member.get("role") == "owner"


@set_leave.handle()
async def leave(bot: Bot, env: EnvelopeNBDep, target: Match[str]):
    raw = str(target.result).strip() if target.available else ""

    if env.is_group:
        if not raw:
            await set_leave.finish("❌ 请输入 --this 离开当前群，或指定群号！")
        if raw == "--this":
            group_id = int(env.scope.id)
        else:
            if not raw.isdigit():
                await set_leave.finish("❌ 请输入一个数字（群号）！")
            group_id = int(raw)
    else:
        if not raw or raw == "--this":
            await set_leave.finish("❌ --this 只允许在群内使用，请指定群号！")
        if not raw.isdigit():
            await set_leave.finish("❌ 请输入一个数字（群号）！")
        group_id = int(raw)

    if await is_group_owner(bot, group_id):
        await set_leave.finish(f"❌ Bot 是群 {group_id} 的群主，无法主动退出该群！")
    await send_to_admin(f"⚠️ 尝试离开群：{group_id}")
    await bot.set_group_leave(group_id=group_id)
    await set_leave.finish(f"✅ 已退出群 {group_id}！")
