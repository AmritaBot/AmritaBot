import platform
from importlib import metadata

from arclet.alconna import Alconna
from nonebot_plugin_alconna import on_alconna

from amrita.config import get_amrita_config
from amrita.plugins.menu.models import MatcherData
from amrita.utils.utils import get_amrita_version, get_core_version, get_sense_version

amrita_cmd = on_alconna(
    Alconna("amrita"),
    aliases={"Amrita", "版本", "关于"},
    use_cmd_start=True,
    priority=10,
    block=True,
    default_state=MatcherData(
        name="Amrita 信息",
        description="查看 Amrita 版本与环境信息",
        usage="/amrita",
    ).model_dump(),
)


@amrita_cmd.handle()
async def _():
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
    await amrita_cmd.finish("\n".join(lines))
