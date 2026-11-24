"""OneBot v11 实现：把 onebot 事件收敛成 Envelope。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.event import (
    Event as OneBotEvent,
)
from nonebot.adapters.onebot.v11.event import (
    MessageEvent as OneBotMessageEvent,
)
from nonebot.adapters.onebot.v11.event import (
    MetaEvent as OneBotMetaEvent,
)
from nonebot.adapters.onebot.v11.event import (
    NoticeEvent as OneBotNoticeEvent,
)
from nonebot.adapters.onebot.v11.event import (
    RequestEvent as OneBotRequestEvent,
)
from pydantic import BaseModel

from ...dto import (
    MESSAGE,
    META,
    NOTICE,
    REQUEST,
    UNKNOWN,
    Actor,
    Envelope,
    Part,
    Scope,
)
from ...ports import (
    CAP_AT,
    CAP_IMAGE,
    CAP_RECALL,
    CAP_REPLY,
    CAP_TEXT,
    BaseSender,
)
from .common import QQ, dedupe_key, normalize_role, segments_to_parts

_ADAPTER_MODULE = "nonebot.adapters.onebot"


class _OneBotGroupAPI(Protocol):
    """onebot v11 的群成员查询走 __getattr__ 动态 API，静态只能这样描述。"""

    async def get_group_member_info(
        self, *, group_id: int, user_id: int, no_cache: bool = ...
    ) -> dict[str, object]: ...


class OneBotSender(BaseSender):
    """把 Bot 包起来，外部只看得到能力。"""

    def __init__(self, bot: Bot, scope: Scope) -> None:
        # 端口只认框架基类，具体类型在实现内部收窄；运行期按鸭子类型使用。
        self._bot = cast(OneBotBot, bot)
        self.scope = scope
        caps = {CAP_TEXT, CAP_IMAGE, CAP_RECALL}
        if scope.is_group:
            caps |= {CAP_AT, CAP_REPLY}
        self.capabilities = frozenset(caps)

    async def send_text(
        self,
        text: str,
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        self._require(CAP_TEXT)
        segments: list[MessageSegment] = []
        if reply_to and self.supports(CAP_REPLY):
            segments.append(MessageSegment.reply(int(reply_to)))
        segments.append(MessageSegment.text(text))
        return await self._send(Message(segments))

    async def send_parts(
        self,
        parts: Sequence[Part],
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        segments: list[MessageSegment] = []
        if reply_to and self.supports(CAP_REPLY):
            segments.append(MessageSegment.reply(int(reply_to)))
        for part in parts:
            match part.kind:
                case "text":
                    segments.append(MessageSegment.text(part.value))
                case "image" if self.supports(CAP_IMAGE):
                    segments.append(MessageSegment.image(part.value))
                case "at" if self.supports(CAP_AT):
                    segments.append(MessageSegment.at(part.value))
                case "at":
                    # 私聊没有 @ 语义，降级成文本。
                    segments.append(MessageSegment.text(f"@{part.value} "))
                case "reply" if self.supports(CAP_REPLY):
                    segments.append(MessageSegment.reply(int(part.value)))
                case _:
                    segments.append(MessageSegment.text(part.value))
        return await self._send(Message(segments))

    async def recall(self, message_id: str) -> bool:
        if not self.supports(CAP_RECALL):
            return False
        try:
            await self._bot.delete_msg(message_id=int(message_id))
        except Exception:  # 撤回失败是常态（超时/无权限/已过期）
            return False
        return True

    async def _send(self, message: Message) -> str:
        if self.scope.is_group:
            resp = await self._bot.send_group_msg(
                group_id=int(self.scope.id), message=message
            )
        else:
            resp = await self._bot.send_private_msg(
                user_id=int(self.scope.id), message=message
            )
        if isinstance(resp, dict):
            return str(resp.get("message_id", ""))
        return str(getattr(resp, "message_id", ""))


def _user_id(event: OneBotEvent) -> str | None:
    """事件发起者 ID；meta 事件（心跳/生命周期）没有发起者，返回 None。

    不能直接用 ``event.get_user_id()``：它对没有上下文的事件抛 ValueError，
    而 meta 事件会走同一个归一化入口。
    """
    for holder in (event, getattr(event, "sender", None)):
        value = getattr(holder, "user_id", None)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value:
            return value
    return None


class OneBotPort:
    name = QQ
    adapter = "onebot11"

    def match(self, raw_event: BaseModel, bot: Bot | None = None) -> bool:
        module = type(raw_event).__module__
        return module.startswith(_ADAPTER_MODULE) and isinstance(raw_event, OneBotEvent)

    def to_envelope(self, raw_event: BaseModel, bot: Bot | None = None) -> Envelope:
        if not isinstance(raw_event, OneBotEvent):
            raise TypeError(f"not an onebot event: {type(raw_event)!r}")
        event = raw_event
        if isinstance(event, OneBotMessageEvent):
            kind = MESSAGE
        elif isinstance(event, OneBotNoticeEvent):
            kind = NOTICE
        elif isinstance(event, OneBotRequestEvent):
            kind = REQUEST
        elif isinstance(event, OneBotMetaEvent):
            kind = META
        else:
            kind = UNKNOWN

        scope = self._scope(event)
        actor = self._actor(event)
        parts = (
            segments_to_parts(event.get_message())
            if isinstance(event, OneBotMessageEvent)
            else ()
        )
        return Envelope(
            kind=kind,
            scope=scope,
            actor=actor,
            parts=parts,
            ts=float(event.time),
            dedupe_key=self._dedupe(event, kind, scope, actor),
            message_id=(
                str(event.message_id) if isinstance(event, OneBotMessageEvent) else ""
            ),
            reply_to=(
                str(event.reply.message_id)
                if isinstance(event, OneBotMessageEvent) and event.reply
                else None
            ),
            self_id=str(event.self_id),
            raw=event,
            adapter=self.adapter,
        )

    def sender(self, bot: Bot, scope: Scope) -> OneBotSender:
        return OneBotSender(bot, scope)

    async def resolve_role(self, bot: Bot, scope: Scope, actor: Actor) -> Actor:
        if actor.role_known or not scope.is_group:
            return actor
        api = cast(_OneBotGroupAPI, bot)
        try:
            info = await api.get_group_member_info(
                group_id=int(scope.id), user_id=int(actor.user_id), no_cache=True
            )
        except Exception:  # 查不到就是查不到，不猜
            return actor
        role = info.get("role")
        if not isinstance(role, str):
            return actor
        return Actor(
            platform=actor.platform,
            user_id=actor.user_id,
            nickname=actor.nickname,
            role=normalize_role(role),
            role_known=True,
        )

    @staticmethod
    def _scope(event: OneBotEvent) -> Scope:
        group_id = getattr(event, "group_id", None)
        if isinstance(group_id, int) and group_id:
            return Scope(platform=QQ, kind="group", id=str(group_id))
        #  meta 事件没有发送者，退到机器人自身，别让 get_user_id 抛出去
        return Scope(
            platform=QQ, kind="private", id=_user_id(event) or str(event.self_id)
        )

    @staticmethod
    def _actor(event: OneBotEvent) -> Actor:
        nickname: str | None = None
        role: str | None = None
        sender = getattr(event, "sender", None)
        if sender is not None:
            card = getattr(sender, "card", None)
            name = getattr(sender, "nickname", None)
            if isinstance(card, str) and card:
                nickname = card
            elif isinstance(name, str):
                nickname = name
            role = getattr(sender, "role", None)
        user_id = _user_id(event) or str(event.self_id)
        return Actor(
            platform=QQ,
            user_id=user_id,
            nickname=nickname,
            role=normalize_role(role if isinstance(role, str) else None),
            role_known=isinstance(role, str),
            is_bot=user_id == str(event.self_id),
        )

    @staticmethod
    def _dedupe(event: OneBotEvent, kind: str, scope: Scope, actor: Actor) -> str:
        if kind == MESSAGE:
            return dedupe_key(QQ, "msg", getattr(event, "message_id", ""))
        notice_type = getattr(event, "notice_type", "")
        return dedupe_key(QQ, str(notice_type), scope.id, actor.user_id, event.time)
