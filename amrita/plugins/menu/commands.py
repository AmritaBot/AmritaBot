"""菜单展示命令：Alconna 解析 --sudo，出站走公共转发/降级底座。"""

from __future__ import annotations

from arclet.alconna import Alconna, Option
from nonebot.adapters import Bot
from nonebot_plugin_alconna import AlconnaResult, CommandResult, on_alconna

from amrita.config import get_amrita_config
from amrita.platform.di import EnvelopeNBDep
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.send import send_forward_msg

from .manager import menu_mamager
from .models import MatcherData
from .utils import generate_menu

menu_cmd = on_alconna(
    Alconna("menu", Option("--sudo")),
    aliases={"菜单", "help"},
    use_cmd_start=True,
    priority=10,
    block=True,
    default_state=MatcherData(
        name="Menu",
        description="展示菜单",
        usage="/menu [--sudo]",
    ).model_dump(),
    rule=lambda: not get_amrita_config().disable_builtin_menu,
)


@menu_cmd.handle()
async def show_menu(
    bot: Bot,
    env: EnvelopeNBDep,
    result: CommandResult = AlconnaResult(),
):
    """显示菜单（/menu --sudo 需要 lp.admin 权限展示完整菜单）。"""
    if not menu_mamager.plugins:
        await menu_cmd.finish("菜单加载失败，请检查日志")

    sudo = bool(result.result.find("sudo"))
    if sudo and not await is_lp_admin(env):
        await menu_cmd.finish("❌ 无权限查看管理员菜单（需要 lp.admin 权限）")

    menu_datas = await generate_menu(
        menu_mamager.plugins,
        event=env,
        sudo=sudo,
    )

    if not menu_datas:
        await menu_cmd.finish("没有可用的菜单")

    await send_forward_msg(
        bot,
        env,
        name="Menu",
        uin=env.self_id or str(bot.self_id),
        msgs=menu_datas,
    )
