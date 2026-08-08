from nonebot import get_driver, logger, on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from amrita import get_amrita_config
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin

clean_groups = on_command(
    "clean_groups",
    permission=is_lp_admin,
    state=MatcherData(
        name="无用群组清理",
        description="清理人数小于20的无效聊群",
        usage="/clean_groups",
        show_if="lp.admin",
    ).model_dump(),
)


@clean_groups.handle()
async def _(bot: Bot, event: MessageEvent):
    await clean_groups.send("⚠️ 开始清理低群人数群组...")
    groups = await bot.get_group_list()
    for group in groups:
        try:
            members: set[int] = {
                member["user_id"]
                for member in await bot.get_group_member_list(
                    group_id=group["group_id"]
                )
            }
        except Exception as e:
            logger.error(f"⚠️ 获取群成员信息失败: {e!s}")
            continue
        admins = {int(i) for i in get_driver().config.superusers if i.isdigit()}

        if len(members) < 20:
            admin_members = members & admins
            if len(admin_members) > 0:
                await clean_groups.send(
                    f"⚠️ 群组 {group['group_name']} ({group['group_id']}) 人数小于20,但有 {len(admin_members)} 个Bot管理员，跳过"
                )
                continue
            await clean_groups.send(
                f"⚠️ 尝试退出群组{group['group_name']}({group['group_id']})....."
            )
            try:
                await bot.send_group_msg(
                    group_id=group["group_id"],
                    message=f"⚠️ 该群人数小于二十人！Bot将退出该群组。{f'如有疑问请加群{get_amrita_config().public_group}' if get_amrita_config().public_group else ''}。",
                )
            except Exception as e:
                logger.error(f"⚠️ 发送退群通知失败: {e!s}")
            try:
                await bot.set_group_leave(group_id=group["group_id"])
            except Exception as e:
                logger.error(f"⚠️ 退出群组失败: {e!s}")
