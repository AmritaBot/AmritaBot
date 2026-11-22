"""Telegram 出站实现：能力表如实声明，不支持的组合明确降级而不是假装成功。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from nonebot.adapters import Bot

from ...dto import CHANNEL, GROUP, Part, Scope
from ...ports import (
    CAP_EDIT,
    CAP_IMAGE,
    CAP_RECALL,
    CAP_REPLY,
    CAP_TEXT,
    CAP_THREAD,
    CAP_TYPING,
    BaseSender,
)
from .api import Outgoing, TelegramAPI, chat_id, load_api, thread_id

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
# Telegram 上限 4096 字符，留点余量给换行与实体
_TEXT_LIMIT = 4000


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


def _chunks(text: str) -> list[str]:
    """超长正文按段落边界切分，Telegram 单条上限之外的内容不会被静默截断。"""
    if len(text) <= _TEXT_LIMIT:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > _TEXT_LIMIT:
        cut = rest.rfind("\n", 0, _TEXT_LIMIT)
        if cut < _TEXT_LIMIT // 2:
            cut = _TEXT_LIMIT
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks


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
        reply_id = self._resolve_reply_id((), reply_to)
        first_id = ""
        for index, chunk in enumerate(_chunks(text)):
            segments: list[Outgoing] = []
            if index == 0 and reply_id is not None:
                segments.append(api.Reply.reply(reply_id))
            segments.append(api.Entity.text(chunk))
            message_id = await self._send(api.Message(segments), thread=thread)
            if index == 0:
                first_id = message_id
        return first_id

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
        reply_id = self._resolve_reply_id(parts, reply_to)
        groups = self._group_parts(parts)
        if not groups:
            return ""  # 只有引用段没有正文，发出去只会被 Telegram 拒
        first_id = ""
        for index, group in enumerate(groups):
            segments: list[Outgoing] = []
            if index == 0 and reply_id is not None:
                segments.append(api.Reply.reply(reply_id))
            for part in group:
                segment = self._segment(part, api)
                if segment is not None:
                    segments.append(segment)
            if not segments:
                continue
            message_id = await self._send(api.Message(segments), thread=thread)
            if index == 0:
                first_id = message_id
        return first_id

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
        text = "".join(part.value for part in parts if part.kind == "text")
        if len(text) > _TEXT_LIMIT:
            # 编辑只能原地替换，拆条会变成新消息，不如如实失败让调用方改走发送
            return False
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

    def _segment(self, part: Part, tg: TelegramAPI) -> Outgoing | None:
        match part.kind:
            case "text":
                return tg.Entity.text(part.value)
            case "reply":
                return None  # 引用已统一处理，避免重复 ReplyParameters
            case "at":
                # Telegram 只能按 username 提及；裸数字 id 发出去就是假 @，直接不生成
                return (
                    None if part.value.isdigit() else tg.Entity.text(f"@{part.value} ")
                )
            case _ if part.kind in _MEDIA_KINDS:
                # 一律用 File：UnCombinFile 走 adapter 的 others 分支会把参数名写成 file，
                # Telegram 只认 sticker=/video_note=，单独成条由 _group_parts 保证
                return tg.File(_MEDIA_KINDS[part.kind], {"file": _part_value(part)})
            case _:
                return tg.Entity.text(part.value)

    def _group_parts(self, parts: Sequence[Part]) -> list[list[Part]]:
        """把 parts 切成若干条可发送的消息，贴纸/视频留言与超长文本各自成条。"""
        groups: list[list[Part]] = []
        current: list[Part] = []
        budget = _TEXT_LIMIT
        for part in parts:
            if part.kind == "reply":
                continue
            if part.kind in _UNCOMBINABLE:
                if current:
                    groups.append(current)
                    current = []
                    budget = _TEXT_LIMIT
                groups.append([part])
                continue
            if part.kind != "text":
                current.append(part)
                continue
            for chunk in _chunks(part.value):
                if len(chunk) > budget:
                    if current:
                        groups.append(current)
                    current = []
                    budget = _TEXT_LIMIT
                current.append(Part(kind="text", value=chunk))
                budget -= len(chunk)
        if current:
            groups.append(current)
        return groups

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
        """相册会返回多条消息 id，契约只带得回第一条，其余不跟踪。"""
        resp = await self._bot.send_to(
            chat_id(self.scope),
            message,
            message_thread_id=thread_id(self.scope, thread),
        )
        if isinstance(resp, Sequence) and not isinstance(resp, str | bytes):
            resp = resp[0] if resp else None
        return str(getattr(resp, "message_id", "") or "")

    async def _send_plain(self, text: str, *, thread: str | None) -> str:
        first_id = ""
        for index, chunk in enumerate(_chunks(text)):
            resp = await self._bot.send_message(
                chat_id=chat_id(self.scope),
                text=chunk,
                message_thread_id=thread_id(self.scope, thread),
            )
            if index == 0:
                first_id = str(getattr(resp, "message_id", "") or "")
        return first_id


__all__ = ["TelegramBot", "TelegramSender"]
