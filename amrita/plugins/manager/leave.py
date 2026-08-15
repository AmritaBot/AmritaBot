from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.admin import send_to_admin


async def is_group_owner(bot: Bot, group_id: int) -> bool:
    """检测 Bot 是否为指定群的群主（群主无法主动退群）"""
    try:
        member = await bot.get_group_member_info(
            group_id=group_id, user_id=int(bot.self_id)
        )
    except Exception:
        return False
    return member.get("role") == "owner"


@on_command(
    "set_leave",
    permission=is_lp_admin,
    state=MatcherData(
        name="退出指定群聊",
        description="用于退出群聊",
        usage="/set_leave [<group-id>|--this]",
        show_if="lp.admin",
    ).model_dump(),
).handle()
async def leave(
    bot: Bot, matcher: Matcher, event: MessageEvent, arg: Message = CommandArg()
):
    str_id = arg.extract_plain_text().strip()
    if isinstance(event, GroupMessageEvent):
        if not str_id:
            await matcher.finish("❌ 请输入 --this 离开当前群，或指定群号！")
        if str_id == "--this":
            group_id: int | None = event.group_id
        else:
            if not str_id.isdigit():
                await matcher.finish("❌ 请输入一个数字（群号）！")
            group_id = int(str_id)
    else:
        if not str_id or str_id == "--this":
            await matcher.finish("❌ --this 只允许在群内使用，请指定群号！")
        if not str_id.isdigit():
            await matcher.finish("❌ 请输入一个数字（群号）！")
        group_id = int(str_id)

    if await is_group_owner(bot, group_id):
        await matcher.finish(f"❌ Bot 是群 {group_id} 的群主，无法主动退出该群！")
    await send_to_admin(f"⚠️ 尝试离开群：{group_id}")
    await bot.set_group_leave(group_id=group_id)
    await matcher.finish(f"✅ 已退出群 {group_id}！")
