import typing

from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment

from .events import event_user_id


async def send_forward_msg(
    bot: Bot, event: Event, name: str, uin: str, msgs: typing.Iterable[MessageSegment]
):
    def to_json(msg: MessageSegment) -> dict:
        return {"type": "node", "data": {"name": name, "uin": uin, "content": msg}}

    messages = [to_json(msg) for msg in msgs]
    if (gid := getattr(event, "group_id", None)) is not None:
        await bot.send_group_forward_msg(group_id=gid, messages=messages)
    else:
        user_id = event_user_id(event)
        if user_id is None:
            raise ValueError("event has no user id")
        await bot.send_private_forward_msg(user_id=int(user_id), messages=messages)
