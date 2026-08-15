from nonebot import CommandGroup
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.params import CommandArg

from amrita.plugins.menu.models import (
    MatcherData,
)
from amrita.plugins.perm.API.admin import is_lp_admin

send = CommandGroup("send_to", permission=is_lp_admin)

group = send.command(
    "group",
    state=MatcherData(
        name="推送群消息",
        description="用于向一个群发送消息",
        usage="/send_to.group [群号] [消息]",
        show_if="lp.admin",
    ).model_dump(),
)
user = send.command(
    "user",
    state=MatcherData(
        name="推送私聊消息",
        description="用于向一个用户发送消息",
        usage="/send_to.user [用户ID] [消息]",
        show_if="lp.admin",
    ).model_dump(),
)


@group.handle()
async def _(bot: Bot, args: Message = CommandArg()):
    arg_list = args.extract_plain_text().strip().split(maxsplit=1)
    if len(arg_list) < 2:
        await group.finish("❌ 请输入群号和消息")
    try:
        assert arg_list[0].isdigit(), "群号只能为数字"
        await bot.send_group_msg(group_id=int(arg_list[0]), message=arg_list[1])
    except Exception as e:
        await group.finish(f"❌ {e}发送失败。")


@user.handle()
async def _(bot: Bot, args: Message = CommandArg()):
    arg_list = args.extract_plain_text().strip().split(maxsplit=1)
    if len(arg_list) < 2:
        await user.finish("❌ 请输入用户ID和消息")
    try:
        assert arg_list[0].isdigit(), "用户ID只能为数字"
        await bot.send_private_msg(user_id=int(arg_list[0]), message=arg_list[1])
    except Exception as e:
        await user.finish(f"❌ {e}发送失败。")
