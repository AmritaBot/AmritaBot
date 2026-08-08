from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.admin import send_to_admin


@on_command(
    "set_leave",
    permission=is_lp_admin,
    state=MatcherData(
        name="退出指定聊群",
        description="用于退出聊群",
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
            await matcher.finish("⚠️ 请输入--this来离开这个群！或者指定群号！")
        if str_id == "--this":
            await send_to_admin(f"⚠️ 尝试离开群：{event.group_id}")
            await matcher.send("✅ 已退出本群！")
            await bot.set_group_leave(group_id=event.group_id)
            return
    if str_id != "--this":
        try:
            int(str_id)
        except Exception:
            await matcher.finish("⚠️ 请输入一个数字")
        else:
            await matcher.send(f"⚠️ 尝试离开{str_id}")
            await bot.set_group_leave(group_id=int(str_id))
    else:
        await matcher.finish("⚠️ 该参数只允许在群内使用！")
