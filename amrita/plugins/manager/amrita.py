import platform
from importlib import metadata

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from amrita.config import get_amrita_config
from amrita.utils.utils import get_amrita_version, get_core_version

amrita = on_command("amrita", aliases={"Amrita"}, priority=10, block=True)


@amrita.handle()
async def _(matcher: Matcher, event: MessageEvent):
    conf = get_amrita_config()
    if conf.no_amrita_flag:
        return

    # 获取 sense 版本
    try:
        sense_version = metadata.version("amrita-sense")
    except metadata.PackageNotFoundError:
        sense_version = "N/A"

    # 获取 NoneBot2 版本
    try:
        nb_version = metadata.version("nonebot2")
    except metadata.PackageNotFoundError:
        nb_version = "N/A"

    os_name = platform.system()  # Linux / Windows / Darwin
    lines = [
        f"系统环境: {os_name}",
        f"Amrita版本: v{get_amrita_version()}",
        f"Core运行时版本: v{get_core_version()} (Sense: v{sense_version})",
        f"NoneBot2版本: v{nb_version}",
    ]
    await matcher.finish("\n".join(lines))
