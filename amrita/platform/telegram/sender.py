"""Telegram 出站实现：能力表如实声明，不支持的组合明确降级而不是假装成功。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from nonebot.adapters import Bot

from ..dto import CHANNEL, GROUP, Part, Scope
from ..ports import (
    CAP_EDIT,
    CAP_IMAGE,
    CAP_RECALL,
    CAP_REPLY,
    CAP_TEXT,
    CAP_THREAD,
    CAP_TYPING,
    BaseSender,
)
from .api import Outgoing, chat_id, load_api, thread_id

# 同义归一：photo 与 QQ 的 image 是同一件事；其余保留平台原始类型名
_MEDIA_KINDS = {
    "image": "photo",
    "voice": "voice",
    "audio": "audio",
    "animation": "animation",
    "document": "document",
    "video": "video",
    "sticker": "sticker",
    "video_note": "video_note",
}
# 这两类在适配器里必须单独发送，不能和别的段组合
_UNCOMBINABLE = {"sticker", "video_note"}


class TelegramBot(Protocol):
    """只描述用到的几个方法，避免把 Bot 当万能对象使用。"""

    async def send_to(
        self,
        chat_id: int | str,
        message: object,
        message_thread_id: int | None = None,
    ) -> object: ...

    async def send_message(
        self, *, chat_id: int | str, text: str, message_thread_id: int | None = None
    ) -> object: ...

    async def delete_message(
        self, *, chat_id: int | str, message_id: int
    ) -> object: ...

    async def edit_message_text(
        self, *, text: str, chat_id: int | str, message_id: int
    ) -> object: ...

    async def send_chat_action(
        self,
        *,
        chat_id: int | str,
        action: str,
        message_thread_id: int | None = None,
    ) -> object: ...

    async def get_chat_member(self, *, chat_id: int | str, user_id: int) -> object: ...


def _part_value(part: Part) -> str:
    if part.value:
        return part.value
    file_id = part.meta.get("file_id")
    return file_id if isinstance(file_id, str) else ""


class TelegramSender(BaseSender):
    def __init__(self, bot: Bot, scope: Scope) -> None:
        self._bot = cast(TelegramBot, bot)
        self.scope = scope
        caps = {CAP_TEXT, CAP_IMAGE, CAP_RECALL, CAP_EDIT, CAP_TYPING}
        if scope.kind != CHANNEL:
            # 频道是单向广播，回复在 Telegram 侧本来就不存在
            caps.add(CAP_REPLY)
        if scope.kind == GROUP:
            # 论坛话题靠 message_thread_id 分桶，普通群传了也会被忽略
            caps.add(CAP_THREAD)
        self.capabilities = frozenset(caps)

    async def send_text(
        self,
        text: str,
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        self._require(CAP_TEXT)
        api = load_api()
        if api is None:
            # 没装适配器时只可能是外部伪造的 Bot，退化为纯文本直发
            return await self._send_plain(text, thread=thread)
        segments: list[Outgoing] = []
        reply_id = self._resolve_reply_id((), reply_to)
        if reply_id is not None:
            segments.append(api.Reply.reply(reply_id))
        segments.append(api.Entity.text(text))
        return await self._send(api.Message(segments), thread=thread)

    async def send_parts(
        self,
        parts: Sequence[Part],
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        self._require(CAP_TEXT)
        api = load_api()
        if api is None:
            return await self._send_plain(
                "".join(p.value for p in parts if p.kind == "text"), thread=thread
            )
        if not any(part.kind != "reply" for part in parts):
            return ""  # 只有引用段没有正文，发出去只会被 Telegram 拒
        segments: list[Outgoing] = []
        reply_id = self._resolve_reply_id(parts, reply_to)
        if reply_id is not None:
            segments.append(api.Reply.reply(reply_id))
        for part in parts:
            match part.kind:
                case "text":
                    segments.append(api.Entity.text(part.value))
                case "reply":
                    continue  # 引用已在上面统一处理，避免重复 ReplyParameters
                case "at":
                    # Telegram 的 @ 只能按 username 文本发送，没有按 id 寻址的能力
                    segments.append(api.Entity.text(f"@{part.value} "))
                case _ if part.kind in _MEDIA_KINDS:
                    seg_type = _MEDIA_KINDS[part.kind]
                    factory = (
                        api.UnCombinFile if part.kind in _UNCOMBINABLE else api.File
                    )
                    segments.append(factory(seg_type, {"file": _part_value(part)}))
                case _:
                    segments.append(api.Entity.text(part.value))
        return await self._send(api.Message(segments), thread=thread)

    async def recall(self, message_id: str) -> bool:
        if not self.supports(CAP_RECALL):
            return False
        try:
            await self._bot.delete_message(
                chat_id=chat_id(self.scope), message_id=int(message_id)
            )
        except Exception:  # 撤回失败是常态：超时、无权限、超过 48 小时
            return False
        return True

    async def edit(self, message_id: str, parts: Sequence[Part]) -> bool:
        if not self.supports(CAP_EDIT):
            return False
        if any(part.kind not in {"text", "reply", "at"} for part in parts):
            # 带媒体只能走 edit_message_caption，两个 API 的语义不同，不混着猜
            return False
        text = "".join(
            f"@{part.value} " if part.kind == "at" else part.value
            for part in parts
            if part.kind in {"text", "at"}
        )
        try:
            await self._bot.edit_message_text(
                text=text, chat_id=chat_id(self.scope), message_id=int(message_id)
            )
        except Exception:
            return False
        return True

    async def typing(self) -> None:
        if not self.supports(CAP_TYPING):
            return
        try:
            await self._bot.send_chat_action(
                chat_id=chat_id(self.scope),
                action="typing",
                message_thread_id=thread_id(self.scope),
            )
        except Exception:  # 输入指示失败不值得打断主链路
            return

    def _resolve_reply_id(
        self, parts: Sequence[Part], reply_to: str | None
    ) -> int | None:
        if not self.supports(CAP_REPLY):
            return None
        raw = reply_to
        if raw is None:
            raw = next(
                (part.value for part in parts if part.kind == "reply" and part.value),
                None,
            )
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    async def _send(self, message: Outgoing, *, thread: str | None) -> str:
        resp = await self._bot.send_to(
            chat_id(self.scope),
            message,
            message_thread_id=thread_id(self.scope, thread),
        )
        if isinstance(resp, Sequence) and not isinstance(resp, str | bytes):
            resp = resp[0] if resp else None
        return str(getattr(resp, "message_id", "") or "")

    async def _send_plain(self, text: str, *, thread: str | None) -> str:
        resp = await self._bot.send_message(
            chat_id=chat_id(self.scope),
            text=text,
            message_thread_id=thread_id(self.scope, thread),
        )
        return str(getattr(resp, "message_id", "") or "")


__all__ = ["TelegramBot", "TelegramSender"]
