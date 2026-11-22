"""Milky 适配：不 hard-import nonebot.adapters.milky。

原因有两条：

1. adapter-milky 只是可选依赖，没装的时候框架也要能起来；
2. 事件形状是稳定的（``data.message_scene`` / ``data.peer_id`` / ``data.sender_id``），
   按形状判断比按类名判断更抗版本变化。

消息段构造是唯一需要具体类的地方，延迟到发送时才 import；类型用 Protocol 描述。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Protocol, cast

from nonebot.adapters import Bot
from pydantic import BaseModel

from ..dto import (
    MESSAGE,
    META,
    NOTICE,
    REQUEST,
    UNKNOWN,
    Actor,
    Envelope,
    MetaValue,
    Part,
    Scope,
)
from ..ports import (
    CAP_AT,
    CAP_IMAGE,
    CAP_RECALL,
    CAP_REPLY,
    CAP_TEXT,
    BaseSender,
)
from .common import QQ, SegmentLike, dedupe_key, normalize_role, segment_to_part

_ADAPTER_MODULE = "nonebot.adapters.milky"
_MESSAGE_SCENES = {"friend", "group", "temp"}


# ------------------------------------------------------------------ 出站协议


class _MilkyOutgoing(Protocol):
    def to_elements(self) -> list[dict[str, MetaValue]]: ...


class _MilkyFragments(Protocol):
    @staticmethod
    def text(content: str) -> _MilkyOutgoing: ...

    @staticmethod
    def mention(user_id: int) -> _MilkyOutgoing: ...

    @staticmethod
    def reply(message_seq: int) -> _MilkyOutgoing: ...

    @staticmethod
    def image(url: str | None = None) -> _MilkyOutgoing: ...


class _MilkyMessageFactory(Protocol):
    def __call__(self, segments: Sequence[_MilkyOutgoing]) -> _MilkyOutgoing: ...


class _MilkyResponse(Protocol):
    message_seq: int


class _MilkyMember(Protocol):
    role: str


class _MilkyBot(Protocol):
    async def get_group_member_info(
        self, *, group_id: int, user_id: int, no_cache: bool = ...
    ) -> _MilkyMember: ...

    async def send_group_message(
        self, *, group_id: int, message: str | _MilkyOutgoing
    ) -> _MilkyResponse: ...

    async def send_private_message(
        self, *, user_id: int, message: str | _MilkyOutgoing
    ) -> _MilkyResponse: ...

    async def recall_group_message(
        self, *, group_id: int, message_seq: int
    ) -> None: ...

    async def recall_private_message(
        self, *, user_id: int, message_seq: int
    ) -> None: ...


def _load_factories() -> tuple[_MilkyMessageFactory, _MilkyFragments] | None:
    try:
        module = import_module("nonebot.adapters.milky.message")
    except ImportError:
        return None
    message = cast(_MilkyMessageFactory, getattr(module, "Message"))
    fragments = cast(_MilkyFragments, getattr(module, "MessageSegment"))
    return message, fragments


# ------------------------------------------------------------------ 形状读取


def _opt_str(obj: BaseModel, name: str) -> str | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else None


def _opt_int(obj: BaseModel, name: str) -> int | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, int) else None


def _raw_data(raw_event: BaseModel) -> BaseModel | None:
    data = getattr(raw_event, "data", None)
    return data if data is not None else None


def _event_type(raw_event: BaseModel) -> str:
    getter = getattr(raw_event, "get_type", None)
    if callable(getter):
        try:
            result = getter()
        except Exception:
            return ""
        return result if isinstance(result, str) else ""
    return ""


def _part_of(item: Mapping[str, MetaValue]) -> Part | None:
    """裸 dict 段（``{"type": ..., "data": {...}}``）→ Part。"""
    seg_type = item.get("type")
    seg_data = item.get("data")
    if isinstance(seg_type, str) and isinstance(seg_data, Mapping):
        return segment_to_part(_MappingSegment(seg_type, seg_data))
    return None


class _MappingSegment:
    """把 milky 的裸 dict 段适配成 :class:`SegmentLike`。"""

    def __init__(self, seg_type: str, data: Mapping[str, MetaValue]) -> None:
        self.type = seg_type
        self.data = data


class MilkySender(BaseSender):
    def __init__(self, bot: Bot, scope: Scope) -> None:
        self._bot = cast(_MilkyBot, bot)
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
        if reply_to and self.supports(CAP_REPLY):
            return await self.send_parts(
                (Part(kind="reply", value=reply_to), Part(kind="text", value=text))
            )
        return await self._send(text)

    async def send_parts(
        self,
        parts: Sequence[Part],
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        self._require(CAP_TEXT)
        message = self._build_message(parts, reply_to=reply_to)
        return await self._send(message)

    async def recall(self, message_id: str) -> bool:
        if not self.supports(CAP_RECALL):
            return False
        try:
            if self.scope.is_group:
                await self._bot.recall_group_message(
                    group_id=int(self.scope.id), message_seq=int(message_id)
                )
            else:
                await self._bot.recall_private_message(
                    user_id=int(self.scope.id), message_seq=int(message_id)
                )
        except Exception:  # 撤回失败是常态
            return False
        return True

    def _build_message(
        self, parts: Sequence[Part], *, reply_to: str | None = None
    ) -> str | _MilkyOutgoing:
        factories = _load_factories()
        if factories is None:
            # 没装适配器时退化为纯文本拼接，至少不阻塞单测与文本链路。
            return "".join(part.value for part in parts if part.kind == "text")
        message_factory, fragments = factories
        segments: list[_MilkyOutgoing] = []
        if reply_to and self.supports(CAP_REPLY):
            segments.append(fragments.reply(int(reply_to)))
        for part in parts:
            match part.kind:
                case "text":
                    segments.append(fragments.text(part.value))
                case "image" if self.supports(CAP_IMAGE):
                    segments.append(fragments.image(part.value))
                case "at" if self.supports(CAP_AT):
                    segments.append(fragments.mention(int(part.value)))
                case "at":
                    segments.append(fragments.text(f"@{part.value} "))
                case "reply" if self.supports(CAP_REPLY):
                    segments.append(fragments.reply(int(part.value)))
                case _:
                    segments.append(fragments.text(part.value))
        return message_factory(segments)

    async def _send(self, message: str | _MilkyOutgoing) -> str:
        if self.scope.is_group:
            resp = await self._bot.send_group_message(
                group_id=int(self.scope.id), message=message
            )
        else:
            resp = await self._bot.send_private_message(
                user_id=int(self.scope.id), message=message
            )
        if isinstance(resp, Mapping):
            return str(resp.get("message_seq", ""))
        return str(getattr(resp, "message_seq", ""))


class MilkyPort:
    name = QQ
    adapter = "milky"

    def match(self, raw_event: BaseModel, bot: Bot | None = None) -> bool:
        module = type(raw_event).__module__
        if module.startswith(_ADAPTER_MODULE):
            return True
        data = _raw_data(raw_event)
        if data is None or _opt_int(raw_event, "self_id") is None:
            return False
        scene = _opt_str(data, "message_scene")
        return scene in _MESSAGE_SCENES or _opt_int(data, "group_id") is not None

    def to_envelope(self, raw_event: BaseModel, bot: Bot | None = None) -> Envelope:
        data = _raw_data(raw_event)
        scene = _opt_str(data, "message_scene") if data is not None else None
        if scene in _MESSAGE_SCENES:
            kind = MESSAGE
        else:
            kind = {
                "message": MESSAGE,
                "notice": NOTICE,
                "request": REQUEST,
                "meta": META,
            }.get(_event_type(raw_event), UNKNOWN)

        scope = self._scope(raw_event, data, scene)
        actor = self._actor(raw_event, data)
        parts = self._parts(raw_event, data) if kind == MESSAGE else ()
        return Envelope(
            kind=kind,
            scope=scope,
            actor=actor,
            parts=parts,
            ts=float(_opt_int(raw_event, "time") or 0),
            dedupe_key=self._dedupe(raw_event, kind, scope, actor),
            message_id=_message_id(raw_event) if kind == MESSAGE else "",
            raw=raw_event,
            adapter=self.adapter,
        )

    def sender(self, bot: Bot, scope: Scope) -> MilkySender:
        return MilkySender(bot, scope)

    async def resolve_role(self, bot: Bot, scope: Scope, actor: Actor) -> Actor:
        if actor.role_known or not scope.is_group:
            return actor
        api = cast(_MilkyBot, bot)
        try:
            member = await api.get_group_member_info(
                group_id=int(scope.id), user_id=int(actor.user_id), no_cache=True
            )
        except Exception:  # 查不到就是查不到，不猜
            return actor
        role = getattr(member, "role", None)
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
    def _scope(
        raw_event: BaseModel, data: BaseModel | None, scene: str | None
    ) -> Scope:
        peer_id = _opt_int(data, "peer_id") if data is not None else None
        if peer_id is not None:
            return Scope(
                platform=QQ,
                kind="group" if scene == "group" else "private",
                id=str(peer_id),
            )
        group_id = _opt_int(data, "group_id") if data is not None else None
        if group_id is not None:
            return Scope(platform=QQ, kind="group", id=str(group_id))
        return Scope(platform=QQ, kind="private", id=_user_id(raw_event, data))

    @staticmethod
    def _actor(raw_event: BaseModel, data: BaseModel | None) -> Actor:
        nickname = _opt_str(data, "sender_name") if data is not None else None
        role = _opt_str(data, "role") if data is not None else None
        return Actor(
            platform=QQ,
            user_id=_user_id(raw_event, data),
            nickname=nickname,
            role=normalize_role(role),
            role_known=role is not None,
        )

    @staticmethod
    def _parts(raw_event: BaseModel, data: BaseModel | None) -> tuple[Part, ...]:
        message = getattr(raw_event, "message", None)
        if isinstance(message, Sequence) and not isinstance(message, str | bytes):
            parts: list[Part] = []
            for segment in message:
                if isinstance(segment, SegmentLike):
                    parts.append(segment_to_part(segment))
                elif isinstance(segment, Mapping):
                    converted = _part_of(cast(Mapping[str, MetaValue], segment))
                    if converted is not None:
                        parts.append(converted)
            return tuple(parts)
        segments = getattr(data, "segments", None) if data is not None else None
        if isinstance(segments, Sequence) and not isinstance(segments, str | bytes):
            parts = []
            for segment in segments:
                if isinstance(segment, Mapping):
                    converted = _part_of(cast(Mapping[str, MetaValue], segment))
                    if converted is not None:
                        parts.append(converted)
            return tuple(parts)
        return ()

    @staticmethod
    def _dedupe(raw_event: BaseModel, kind: str, scope: Scope, actor: Actor) -> str:
        if kind == MESSAGE:
            message_id = _opt_int(raw_event, "message_id")
            if message_id is None:
                data = _raw_data(raw_event)
                message_id = _opt_int(data, "message_seq") if data is not None else None
            return dedupe_key(QQ, "msg", message_id)
        return dedupe_key(
            QQ,
            _event_type(raw_event) or "notice",
            scope.id,
            actor.user_id,
            _opt_int(raw_event, "time"),
        )


def _message_id(raw_event: BaseModel) -> str:
    value = _opt_int(raw_event, "message_id")
    if value is None:
        data = _raw_data(raw_event)
        value = _opt_int(data, "message_seq") if data is not None else None
    return str(value) if value is not None else ""


def _user_id(raw_event: BaseModel, data: BaseModel | None) -> str:
    getter = getattr(raw_event, "get_user_id", None)
    if callable(getter):
        try:
            result = getter()
        except Exception:
            result = None
        if isinstance(result, str):
            return result
    if data is None:
        return ""
    for attr_name in ("sender_id", "user_id", "initiator_id", "operator_id"):
        value = _opt_int(data, attr_name)
        if value is not None:
            return str(value)
    return ""
