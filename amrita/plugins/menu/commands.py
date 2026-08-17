import nonebot
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.config import get_amrita_config
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.send import send_forward_msg

from .manager import menu_mamager
from .models import MatcherData
from .utils import (
    generate_menu,
)

command_start = get_driver().config.command_start

_menu_aliases: set[str | tuple[str, ...]] = set(
    [f"{prefix}菜单" for prefix in command_start]
    + [f"{prefix}help" for prefix in command_start]
    + [f"{prefix}menu" for prefix in command_start]
)


@nonebot.on_command(
    "menu",
    aliases=_menu_aliases,
    priority=10,
    block=True,
    state=MatcherData(
        name="Menu",
        description="展示菜单",
        usage="/menu [--sudo]",
    ).model_dump(),
    rule=lambda: not get_amrita_config().disable_builtin_menu,
).handle()
async def show_menu(
    matcher: Matcher,
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
):
    """显示菜单（/menu --sudo 需要 lp.admin 权限展示完整菜单）"""
    if not menu_mamager.plugins:
        await matcher.finish("菜单加载失败，请检查日志")

    # sudo 需要 lp.admin 权限
    sudo = "--sudo" in args.extract_plain_text().split()
    if sudo and not await is_lp_admin(event):
        await matcher.finish("❌ 无权限查看管理员菜单（需要 lp.admin 权限）")

    menu_datas = await generate_menu(
        menu_mamager.plugins,
        event=event,
        sudo=sudo,
    )

    if not menu_datas:
        await matcher.finish("没有可用的菜单")

    menu_datas_pics = [
        MessageSegment.text(menu_datas_string) for menu_datas_string in menu_datas
    ]

    await send_forward_msg(
        bot,
        event,
        name="Menu",
        uin=str(bot.self_id),
        msgs=menu_datas_pics,
    )
