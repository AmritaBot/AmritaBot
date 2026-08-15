import platform
from importlib import metadata

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from amrita.config import get_amrita_config
from amrita.plugins.menu.models import MatcherData
from amrita.utils.utils import get_amrita_version, get_core_version, get_sense_version

amrita = on_command(
    "amrita",
    aliases={"Amrita", "版本", "关于"},
    priority=10,
    block=True,
    state=MatcherData(
        name="Amrita 信息",
        description="查看 Amrita 版本与环境信息",
        usage="/amrita",
    ).model_dump(),
)


@amrita.handle()
async def _(matcher: Matcher, event: MessageEvent):
    conf = get_amrita_config()
    if conf.no_amrita_flag:
        return
    nb_version = metadata.version("nonebot2")

    os_name = platform.system()  # Linux / Windows / Darwin
    lines = [
        f"系统环境: {os_name}",
        f"Amrita版本: v{get_amrita_version()}",
        f"Core运行时版本: v{get_core_version()} (Sense: v{get_sense_version()})",
        f"NoneBot2版本: v{nb_version}",
    ]
    await matcher.finish("\n".join(lines))
