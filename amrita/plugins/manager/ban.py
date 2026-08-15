from nonebot import CommandGroup
from nonebot.adapters.onebot.v11 import Message
from nonebot.params import CommandArg

from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin

from .blacklist.black import bl_manager

ban = CommandGroup("ban", permission=is_lp_admin)

ban_group = ban.command(
    "group",
    state=MatcherData(
        name="封禁群",
        usage="/ban.group",
        description="封禁群聊",
        show_if="lp.admin",
    ).model_dump(),
)
ban_user = ban.command(
    "user",
    state=MatcherData(
        name="封禁用户",
        description="用于封禁用户",
        usage="/ban.user <user-id> [原因]",
        show_if="lp.admin",
    ).model_dump(),
)


@ban_group.handle()
async def _(args: Message = CommandArg()):
    arg_list = args.extract_plain_text().strip().split(maxsplit=1)
    if not arg_list:
        await ban_group.finish("❌ 请提供要封禁的群ID！")
    if await bl_manager.is_group_black(arg_list[0]):
        await ban_group.finish("❌ 该群已被封禁！")
    else:
        await bl_manager.group_append(arg_list[0], arg_list[1]) if len(
            arg_list
        ) > 1 else await bl_manager.group_append(arg_list[0])
        await ban_group.finish(f"✅ 封禁群{arg_list[0]}成功！")


@ban_user.handle()
async def ban_user_handle(args: Message = CommandArg()):
    arg_list = args.extract_plain_text().strip().split(maxsplit=1)
    if not arg_list:
        await ban_user.finish("❌ 请提供要封禁的用户ID！")
    if await bl_manager.is_private_black(arg_list[0]):
        await ban_user.finish("❌ 该用户已被封禁！")
    else:
        await bl_manager.private_append(arg_list[0], arg_list[1]) if len(
            arg_list
        ) > 1 else await bl_manager.private_append(arg_list[0])
        await ban_user.finish(f"✅ 封禁用户{arg_list[0]}成功！")
