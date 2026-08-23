from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from nonebot.adapters import Bot, Event, MessageSegment

if TYPE_CHECKING:
    from nonebot_plugin_alconna.uniseg import Segment


async def send_forward_msg_to_target(
    bot: Bot, target: Any, name: str, uin: str, msgs: Iterable[str | MessageSegment | "Segment"]
) -> None:
    """以合并转发形式发送消息到指定目标（OneBotV11 自动路由 forward API）"""
    from nonebot_plugin_alconna.uniseg import (
        CustomNode,
        Reference,
        Text,
        UniMessage,
    )

    content = UniMessage()
    for item in msgs:
        if isinstance(item, str):
            content += Text(item)
        elif isinstance(item, Segment):
            content += item
        else:
            content += UniMessage.of(item.get_message_class()(item), bot=bot)
    nodes = [CustomNode(uid=uin, name=name, content=content)]
    await UniMessage(Reference(nodes=nodes)).send(target=target, bot=bot)


async def send_forward_msg(
    bot: Bot, event: Event, name: str, uin: str, msgs: Iterable[str | MessageSegment | "Segment"]
) -> None:
    """以合并转发形式回复当前事件（跨适配器）"""
    from nonebot_plugin_alconna.uniseg import get_target

    await send_forward_msg_to_target(bot, get_target(event, bot), name, uin, msgs)
