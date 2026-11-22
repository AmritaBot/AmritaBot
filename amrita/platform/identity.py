"""会话身份与 uni_id 映射，格式与既有主键逐字节一致。"""

from __future__ import annotations

import re

from .dto import CHANNEL, GROUP, Scope

QQ_ADAPTER_NAME = "QQPlatform"
_PLATFORM_PREFIX = {
    "qq": QQ_ADAPTER_NAME,
    "telegram": "TelegramPlatform",
}
_PREFIX_TO_PLATFORM = {value: key for key, value in _PLATFORM_PREFIX.items()}
_EXTRA_GROUP = "Group"
_EXTRA_PRIVATE = "Private"
_EXTRA_CHANNEL = "Channel"

_UNI_ID_PATTERN = re.compile(r"^(?:.+?)_(Private|Group|Channel)_(.+)\Z")


def uni_id(scope: Scope) -> str:
    """Scope → 业务层主键。"""
    extra = {
        GROUP: _EXTRA_GROUP,
        CHANNEL: _EXTRA_CHANNEL,
    }.get(scope.kind, _EXTRA_PRIVATE)
    prefix = _PLATFORM_PREFIX.get(scope.platform, f"{scope.platform}Platform")
    return f"{prefix}_{extra}_{scope.id}"


def parse_uni_id(value: str) -> Scope | None:
    """主键 → Scope；未知平台前缀按 qq 兼容处理。"""
    if not isinstance(value, str):
        return None
    if match := _UNI_ID_PATTERN.match(value):
        extra, payload = match.group(1), match.group(2)
        prefix = match.group(0).rsplit("_", 2)[0]
        return Scope(
            platform=_PREFIX_TO_PLATFORM.get(prefix, "qq"),
            kind=GROUP
            if extra == "Group"
            else CHANNEL
            if extra == "Channel"
            else "private",
            id=payload,
        )
    return None


def user_uni_id(platform: str, user_id: str) -> str:
    """私聊主键，供没有群上下文时使用。"""
    prefix = _PLATFORM_PREFIX.get(platform, f"{platform}Platform")
    return f"{prefix}_{_EXTRA_PRIVATE}_{user_id}"


def thread_uni_id(scope: Scope) -> str:
    """带二级会话的显式分桶键；刻意不并入 uni_id，避免历史记录失联。"""
    base = uni_id(scope)
    return f"{base}#{scope.thread}" if scope.thread else base
