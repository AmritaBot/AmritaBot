"""LitePerm 主命令 ``/lp``。"""

from __future__ import annotations

from nonebot.matcher import Matcher
from nonebot_plugin_alconna import Match

from amrita.plugins.menu.models import MatcherData

from ..command_manager import command


@command.command(
    (),
    with_params=True,
    state=MatcherData(
        name="lp主命令",
        description="lp 主命令",
        usage="/lp",
    ).model_dump(),
).handle()
async def lp(matcher: Matcher, params: Match[tuple[str, ...]]):
    args_list = list(params.result) if params.available else []
    if not args_list:
        lp_0_help = "LP LitePerm\n请输入参数\nlp.user\nlp.chat_group\nlp.perm_group"

        await matcher.finish(lp_0_help)
