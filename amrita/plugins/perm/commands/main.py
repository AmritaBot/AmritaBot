from nonebot.adapters.onebot.v11 import Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.plugins.menu.models import MatcherData

from ..command_manager import command


@command.command(
    (),
    state=MatcherData(
        name="lp主命令",
        description="lp 主命令",
        usage="/lp",
    ).model_dump(),
).handle()
async def lp(matcher: Matcher, args: Message = CommandArg()):
    args_list = args.extract_plain_text().strip().split()
    if not args_list:
        lp_0_help = "LP LitePerm\n请输入参数\nlp.user\nlp.chat_group\nlp.perm_group"

        await matcher.finish(lp_0_help)
