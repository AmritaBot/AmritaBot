from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.matcher import Matcher

from amrita.API import send_forward_msg
from amrita.plugins.menu.manager import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin

from .checker import APICalledRepo


@on_command(
    "api_stats",
    aliases={"OneBot状态", "protocol_stats"},
    permission=is_lp_admin,
    state=MatcherData(
        name="api_stats",
        description="获取OneBotV11 API调用状态",
        usage="/api_stats",
        show_if="lp.admin",
    ).model_dump(),
).handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher):
    data = await APICalledRepo().query_all()
    if not data:
        await matcher.finish("📭 暂无 API 调用记录")
    msg = "API情况:\n" + "\n".join(
        [
            f"API:{name},调用次数：{dt[0]!s},失败次数：{dt[0] - dt[1]!s}\n"
            for name, dt in data.items()
        ]
    )
    await send_forward_msg(
        bot, event, "Amrita-Stats", str(event.self_id), [MessageSegment.text(msg)]
    )
