from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from ..utils.app import CachedGroupDataRepository


async def switch(
    event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    arg = args.extract_plain_text().strip()
    dm = CachedGroupDataRepository()
    data = await dm.get_group_config(event.group_id)
    if arg in ("开启", "on", "启用", "enable"):
        if not data.autoreply:
            data.autoreply = True
            await matcher.send("开启FakePeople")
        else:
            await matcher.send("已开启")
    elif arg in ("关闭", "off", "禁用", "disable"):
        if data.autoreply:
            data.autoreply = False
            await matcher.send("关闭FakePeople")
        else:
            await matcher.send("已关闭")
    else:
        await matcher.send("请输入开启或关闭")
    await dm.update_group_config(data)
