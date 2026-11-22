"""Telegram 适配器的最小接口面：延迟 import，未安装时不影响其余平台。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from ..dto import CHANNEL, GROUP, PRIVATE, Scope

ADAPTER_MODULE = "nonebot.adapters.telegram"

# chat.type → Scope.kind；supergroup 是群，channel 是单向广播
CHAT_KINDS = {
    "private": PRIVATE,
    "group": GROUP,
    "supergroup": GROUP,
    "channel": CHANNEL,
}


class Outgoing(Protocol):
    """出站消息段的最小形状（适配器的 Entity / File / Reply 都满足）。"""

    type: str


class EntityAPI(Protocol):
    @staticmethod
    def text(text: str) -> Outgoing: ...


class FileAPI(Protocol):
    def __call__(self, seg_type: str, data: Mapping[str, object]) -> Outgoing: ...

    @staticmethod
    def photo(file: str) -> Outgoing: ...


class ReplyAPI(Protocol):
    @staticmethod
    def reply(message_id: int) -> Outgoing: ...


class MessageFactory(Protocol):
    def __call__(self, segments: Sequence[Outgoing]) -> Outgoing: ...


@dataclass(frozen=True, slots=True)
class TelegramAPI:
    """一次取齐构造出站消息所需的几个符号，避免每个调用点各 import 一遍。"""

    Message: MessageFactory
    Entity: EntityAPI
    File: FileAPI
    UnCombinFile: FileAPI
    Reply: ReplyAPI


_api: TelegramAPI | None = None
_loaded = False


def load_api() -> TelegramAPI | None:
    """加载适配器的消息构造类；没装适配器时返回 ``None``（只试一次）。"""
    global _api, _loaded
    if _loaded:
        return _api
    _loaded = True
    try:
        module = import_module(f"{ADAPTER_MODULE}.message")
    except ImportError:
        return None
    _api = TelegramAPI(
        Message=cast(MessageFactory, getattr(module, "Message")),
        Entity=cast(EntityAPI, getattr(module, "Entity")),
        File=cast(FileAPI, getattr(module, "File")),
        UnCombinFile=cast(FileAPI, getattr(module, "UnCombinFile")),
        Reply=cast(ReplyAPI, getattr(module, "Reply")),
    )
    return _api


def chat_id(scope: Scope) -> int | str:
    """chat id 是整数，只有 @username 形式才是字符串，这里不做猜测。"""
    try:
        return int(scope.id)
    except (TypeError, ValueError):
        return scope.id


def thread_id(scope: Scope, thread: str | None = None) -> int | None:
    """话题/子区 id；Telegram 只接受整数，非法值按"没有话题"处理。"""
    raw = thread if thread is not None else scope.thread
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ADAPTER_MODULE",
    "CHAT_KINDS",
    "TelegramAPI",
    "chat_id",
    "load_api",
    "thread_id",
]
