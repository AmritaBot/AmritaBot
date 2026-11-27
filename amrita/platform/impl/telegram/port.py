"""Telegram 实现：把 nonebot telegram 事件收敛成 Envelope。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from nonebot.adapters import Bot
from nonebot.log import logger
from pydantic import BaseModel

from ...common import dedupe_key, normalize_role
from ...dto import (
    ACTION,
    EDIT,
    GROUP,
    MESSAGE,
    META,
    NOTICE,
    PERM_MANAGE_CHAT,
    PERM_MANAGE_MESSAGES,
    PERM_RESTRICTED,
    PERM_SEND_MESSAGES,
    PRIVATE,
    REQUEST,
    UNKNOWN,
    Actor,
    Envelope,
    MetaValue,
    Part,
    Scope,
)
from .api import ADAPTER_MODULE, CHAT_KINDS, chat_id
from .sender import TelegramBot, TelegramSender

TELEGRAM = "telegram"
ADAPTER_NAME = "telegram"

# 只做同义归一：photo 与 QQ 的 image 是同一件事，其余保留平台原始类型名
_MEDIA_KIND = {"photo": "image"}
_MEDIA_VALUE_KEYS = ("file_id", "file", "emoji", "question", "title")
_KNOWN_ROLES = {"creator", "administrator", "member", "restricted"}


def _opt_str(obj: object, name: str) -> str | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else None


def _opt_int(obj: object, name: str) -> int | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, int) else None


def _jsonable(value: object) -> MetaValue:
    """把 pydantic 模型/嵌套容器压成可 JSON 化的 meta，避免塞进不可序列化对象。"""
    if isinstance(value, BaseModel):
        return cast(MetaValue, value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _utf16_len(text: str) -> int:
    """Telegram 实体的 offset/length 以 UTF-16 码元计，不是码点。"""
    return len(text.encode("utf-16-le")) // 2


def _is_text_segment(segment: object, seg_type: str) -> bool:
    checker = getattr(segment, "is_text", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return seg_type == "text"
    return seg_type == "text"


def _entity(
    type_name: str, offset: int, length: int, data: Mapping[str, MetaValue]
) -> MetaValue:
    entity: dict[str, MetaValue] = {
        "type": type_name,
        "offset": offset,
        "length": length,
    }
    for key in ("url", "language", "custom_emoji_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            entity[key] = value
    user = data.get("user")
    if user is not None:
        entity["user"] = _jsonable(user)
    return entity


def _media_part(seg_type: str, data: Mapping[str, MetaValue]) -> Part:
    value = ""
    for key in _MEDIA_VALUE_KEYS:
        candidate = data.get(key)
        if isinstance(candidate, str | int | float) and str(candidate):
            value = str(candidate)
            break
    if not value:
        for candidate in data.values():
            if isinstance(candidate, str | int | float) and str(candidate):
                value = str(candidate)
                break
    meta: dict[str, MetaValue] = {"type": seg_type, "data": _jsonable(dict(data))}
    file_id = data.get("file_id")
    if isinstance(file_id, str):
        meta["file_id"] = file_id
    mime = data.get("mime_type")
    if isinstance(mime, str):
        meta["mime"] = mime
    return Part(kind=_MEDIA_KIND.get(seg_type, seg_type), value=value, meta=meta)


def parts_of(message: object) -> tuple[Part, ...]:
    """实体分段按 UTF-16 偏移重拼回单个 text Part，格式进 meta["entities"]，文本提及不伪造 at 段。"""
    if not isinstance(message, Sequence) or isinstance(message, str | bytes):
        return ()
    chunks: list[str] = []
    entities: list[MetaValue] = []
    media: list[Part] = []
    offset = 0
    for segment in message:
        seg_type = _opt_str(segment, "type") or ""
        data = getattr(segment, "data", None)
        raw_data: Mapping[str, MetaValue] = (
            cast(Mapping[str, MetaValue], data) if isinstance(data, Mapping) else {}
        )
        if seg_type == "reply":
            continue  # 入站引用走 Envelope.reply_to，不出现在消息段里
        if _is_text_segment(segment, seg_type):
            chunk = str(raw_data.get("text") or "")
            if not chunk:
                continue
            length = _utf16_len(chunk)
            if seg_type != "text":
                entities.append(_entity(seg_type, offset, length, raw_data))
            chunks.append(chunk)
            offset += length
            continue
        media.append(_media_part(seg_type, raw_data))
    parts: list[Part] = []
    if chunks:
        meta: dict[str, MetaValue] = {}
        if entities:
            meta["entities"] = entities
        parts.append(Part(kind="text", value="".join(chunks), meta=meta))
    parts.extend(media)
    return tuple(parts)


def _kind(event: object) -> str:
    getter = getattr(event, "get_type", None)
    raw = getter() if callable(getter) else ""
    match raw:
        case "message":
            return MESSAGE
        case "edit_message":
            return EDIT
        case "notice":
            return NOTICE
        case "request":
            return REQUEST
        case "inline":
            return ACTION
        case "meta":
            return META
        case _:
            return UNKNOWN


def _chat_of(event: object) -> object | None:
    """回调查询的会话可能只挂在 event.message.chat 上，顶层 chat 为空时回退过去。"""
    chat = getattr(event, "chat", None)
    if chat is None:
        chat = getattr(getattr(event, "message", None), "chat", None)
    return chat


def _scope(event: object) -> Scope:
    chat = _chat_of(event)
    chat_type = _opt_str(chat, "type") if chat is not None else None
    if chat_type is not None and chat_type in CHAT_KINDS:
        thread = _opt_int(event, "message_thread_id")
        return Scope(
            platform=TELEGRAM,
            kind=CHAT_KINDS[chat_type],
            id=str(getattr(chat, "id", "")),
            thread=str(thread) if thread is not None else None,
        )
    # 内联查询、按钮回调可能没有 chat，只能退到发起人私聊
    sender = getattr(event, "from_", None)
    user_id = _opt_int(sender, "id") if sender is not None else None
    return Scope(
        platform=TELEGRAM,
        kind=PRIVATE,
        id=str(user_id) if user_id is not None else "",
    )


def _display_name(user: object) -> str | None:
    joined = " ".join(
        part
        for part in (_opt_str(user, "first_name"), _opt_str(user, "last_name"))
        if part
    )
    return joined or _opt_str(user, "username")


def _actor(event: object) -> Actor:
    # 频道帖与匿名管理员会同时带 from 与 sender_chat，from 只是代发的占位账号，主体应取 chat
    sender_chat = getattr(event, "sender_chat", None)
    if sender_chat is not None:
        return Actor(
            platform=TELEGRAM,
            user_id=str(getattr(sender_chat, "id", "")),
            nickname=_opt_str(sender_chat, "title"),
        )
    user = getattr(event, "from_", None)
    if user is not None:
        return Actor(
            platform=TELEGRAM,
            user_id=str(getattr(user, "id", "")),
            nickname=_display_name(user),
            is_bot=bool(getattr(user, "is_bot", False)),
        )
    return Actor(platform=TELEGRAM, user_id="")


def _provenance(event: object) -> Actor | None:
    """转发来源；转发内容一律视为不可信数据。"""
    user = getattr(event, "forward_from", None)
    if user is not None:
        return Actor(
            platform=TELEGRAM,
            user_id=str(getattr(user, "id", "")),
            nickname=_display_name(user),
            is_bot=bool(getattr(user, "is_bot", False)),
        )
    chat = getattr(event, "forward_from_chat", None)
    if chat is not None:
        return Actor(
            platform=TELEGRAM,
            user_id=str(getattr(chat, "id", "")),
            nickname=_opt_str(chat, "title") or _opt_str(chat, "username"),
        )
    name = _opt_str(event, "forward_sender_name")
    if name:
        return Actor(platform=TELEGRAM, user_id="", nickname=name)
    return _origin_provenance(event)


def _origin_provenance(event: object) -> Actor | None:
    """新协议只给 forward_origin，适配器没建字段，只能从原始 update 里取。"""
    model = getattr(event, "telegram_model", None)
    message = getattr(model, "message", None)
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None
    sender = getattr(origin, "sender_user", None)
    if sender is not None:
        return Actor(
            platform=TELEGRAM,
            user_id=str(getattr(sender, "id", "")),
            nickname=_display_name(sender),
            is_bot=bool(getattr(sender, "is_bot", False)),
        )
    chat = getattr(origin, "sender_chat", None) or getattr(origin, "chat", None)
    if chat is not None:
        return Actor(
            platform=TELEGRAM,
            user_id=str(getattr(chat, "id", "")),
            nickname=_opt_str(chat, "title") or _opt_str(chat, "username"),
        )
    hidden = _opt_str(origin, "sender_user_name")
    if hidden:
        return Actor(platform=TELEGRAM, user_id="", nickname=hidden)
    return None


_ACTION_NAMES = {
    "inline.callback_query": "callback",
    "inline.query": "inline_query",
    "inline.chosen_result": "chosen_inline_result",
}


def _action_name(event: object) -> str:
    """Telegram 把内联类事件都挂在 inline 下，这里换成业务侧认得的动作名。"""
    name = _event_name(event)
    return _ACTION_NAMES.get(name, name.rsplit(".", 1)[-1])


def _action_parts(event: object, action: str) -> tuple[Part, ...]:
    if action == "callback":
        data = _opt_str(event, "data")
        return (Part(kind="callback_data", value=data),) if data else ()
    if action == "inline_query":
        query = _opt_str(event, "query")
        return (Part(kind="text", value=query),) if query else ()
    return ()


def _permissions(member: object) -> frozenset[str]:
    status = _opt_str(member, "status")
    permissions: set[str] = set()
    if status == "restricted":
        if getattr(member, "can_send_messages", False):
            permissions.add(PERM_SEND_MESSAGES)
        # 只放开文字但禁了媒体，同样算受限，逐项看而不是只看 can_send_messages
        if any(
            getattr(member, name, True) is False
            for name in (
                "can_send_messages",
                "can_send_audios",
                "can_send_documents",
                "can_send_photos",
                "can_send_videos",
                "can_send_video_notes",
                "can_send_voice_notes",
                "can_send_polls",
                "can_send_other_messages",
            )
        ) or not getattr(member, "is_member", True):
            permissions.add(PERM_RESTRICTED)
    if getattr(member, "can_delete_messages", False) or getattr(
        member, "can_restrict_members", False
    ):
        permissions.add(PERM_MANAGE_MESSAGES)
    if (
        getattr(member, "can_change_info", False)
        or getattr(member, "can_invite_users", False)
        or getattr(member, "can_manage_chat", False)
    ):
        permissions.add(PERM_MANAGE_CHAT)
    return frozenset(permissions)


def _update_id(event: object) -> int | None:
    model = getattr(event, "telegram_model", None)
    return _opt_int(model, "update_id") if model is not None else None


def _event_name(event: object) -> str:
    getter = getattr(event, "get_event_name", None)
    if not callable(getter):
        return ""
    try:
        name = getter()
    except Exception:
        return ""
    return name if isinstance(name, str) else ""


class TelegramPort:
    name = TELEGRAM
    adapter = ADAPTER_NAME

    def match(self, raw_event: BaseModel, bot: Bot | None = None) -> bool:
        if type(raw_event).__module__.startswith(ADAPTER_MODULE):
            return True
        # 形状兜底：chat.type 的取值是 Telegram 独有的，且事件必带 date
        chat = getattr(raw_event, "chat", None)
        chat_type = _opt_str(chat, "type") if chat is not None else None
        if chat_type not in CHAT_KINDS:
            return False
        return _opt_int(raw_event, "date") is not None

    def to_envelope(self, raw_event: BaseModel, bot: Bot | None = None) -> Envelope:
        event = raw_event
        kind = _kind(event)
        scope = _scope(event)
        actor = _actor(event)
        action = ""
        if kind in (MESSAGE, EDIT):
            parts = parts_of(getattr(event, "message", None))
        elif kind == ACTION:
            action = _action_name(event)
            parts = _action_parts(event, action)
        else:
            parts = ()
        message_id = _opt_int(event, "message_id")
        reply = getattr(event, "reply_to_message", None)
        reply_id = _opt_int(reply, "message_id") if reply is not None else None
        ts = _opt_int(event, "date")
        edited_ts = _opt_int(event, "edit_date")
        self_id = _opt_str(event, "self_id") or (
            str(getattr(bot, "self_id", "")) if bot is not None else ""
        )
        return Envelope(
            kind=kind,
            scope=scope,
            actor=actor,
            parts=parts,
            ts=float(ts or 0),
            dedupe_key=self._dedupe(event, kind, scope, actor, ts),
            message_id=str(message_id) if message_id is not None else "",
            reply_to=str(reply_id) if reply_id is not None else None,
            self_id=self_id,
            edited_ts=float(edited_ts) if edited_ts is not None else None,
            provenance=_provenance(event),
            batch_key=_opt_str(event, "media_group_id") or "",
            action=action,
            raw=cast(BaseModel, event),
            adapter=self.adapter,
        )

    def sender(self, bot: Bot, scope: Scope) -> TelegramSender:
        return TelegramSender(bot, scope)

    async def resolve_role(self, bot: Bot, scope: Scope, actor: Actor) -> Actor:
        if actor.role_known or scope.kind != GROUP or not actor.user_id:
            return actor
        if actor.user_id == scope.id:
            # 频道帖 / 匿名管理员的 actor 就是会话本身，get_chat_member 查不了
            return actor
        try:
            user_id = int(actor.user_id)
        except (TypeError, ValueError):
            return actor
        api = cast(TelegramBot, bot)
        try:
            member = await api.get_chat_member(chat_id=chat_id(scope), user_id=user_id)
        except Exception as exc:  # 查不到就是查不到，不猜，但留日志供排查
            logger.warning(
                f"Telegram resolve_role 失败 (chat={scope.id}, user={actor.user_id}): {exc}"
            )
            return actor
        status = _opt_str(member, "status")
        if status is None or status not in _KNOWN_ROLES:
            # left / kicked 不在会话里，没有角色可言，保持"未提供"
            return actor
        return Actor(
            platform=actor.platform,
            user_id=actor.user_id,
            nickname=actor.nickname,
            role=normalize_role(status),
            role_known=True,
            is_bot=actor.is_bot,
            permissions=_permissions(member),
        )

    @staticmethod
    def _dedupe(
        event: object, kind: str, scope: Scope, actor: Actor, ts: int | None
    ) -> str:
        message_id = _opt_int(event, "message_id")
        if kind == MESSAGE:
            # Telegram 的 message_id 只在单个 chat 内唯一，必须带上 chat
            return dedupe_key(TELEGRAM, "msg", scope.id, message_id)
        if kind == EDIT:
            return dedupe_key(
                TELEGRAM,
                "edit",
                scope.id,
                message_id,
                _opt_int(event, "edit_date"),
                _update_id(event),
            )
        # 回调/内联自带唯一 id；同一秒内的多条更新不能只靠秒级时间戳区分
        event_id = _opt_str(event, "id")
        if event_id:
            return dedupe_key(
                TELEGRAM, _event_name(event) or "event", scope.id, event_id
            )
        return dedupe_key(
            TELEGRAM,
            _event_name(event) or "event",
            scope.id,
            _update_id(event),
            ts,
            actor.user_id,
        )


__all__ = ["TelegramPort", "parts_of"]
