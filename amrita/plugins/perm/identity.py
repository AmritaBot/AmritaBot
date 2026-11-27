"""LitePerm 跨平台成员标识归一化：统一收口到 platform.identity 的 uni_id 格式。"""

from __future__ import annotations

from amrita.platform.dto import GROUP, Envelope, Scope
from amrita.platform.identity import parse_uni_id, uni_id, user_uni_id

from .models import PERM_TYPE

DEFAULT_PLATFORM = "qq"


def user_member_id(platform: str, user_id: str) -> str:
    """将平台名与原始用户 ID 归一化为 uni_id（如 ``QQPlatform_Private_123``）。"""
    return user_uni_id(platform, user_id)


def group_member_id(scope: Scope) -> str:
    """将群/频道 Scope 归一化为 uni_id（如 ``QQPlatform_Group_456``）。"""
    return uni_id(scope)


def resolve_member_id(
    raw_id: str,
    member_type: PERM_TYPE,
    *,
    default_platform: str = DEFAULT_PLATFORM,
) -> str:
    """将命令或 API 传入的标识归一化为 uni_id。

    支持三种输入形态：
    1. 已是完整 uni_id（如 ``TelegramPlatform_Group_-100123``）：直接保留；
    2. 带平台前缀 ``<platform>:<raw_id>``（如 ``telegram:-100123``、``qq:12345``）：按指定平台构造；
    3. 裸 ID（如 ``12345``、``-100123``）：默认按 ``default_platform``（命令内为当前会话平台，API/遗留迁移为 ``qq``）构造。
    """
    value = raw_id.strip()
    if not value:
        return value
    if parse_uni_id(value) is not None:
        return value
    platform = default_platform
    payload = value
    if ":" in value:
        prefix, rest = value.split(":", 1)
        if prefix and rest:
            platform = prefix.strip().lower()
            payload = rest.strip()
    if member_type == "group":
        return uni_id(Scope(platform=platform, kind=GROUP, id=payload))
    return user_uni_id(platform, payload)


def envelope_user_member_id(env: Envelope) -> str:
    """提取事件发起者的跨平台用户主键。"""
    return user_member_id(env.actor.platform, env.actor.user_id)


def envelope_group_member_id(env: Envelope) -> str:
    """提取事件会话的跨平台群主键。"""
    return group_member_id(env.scope)


def matches_superuser(env: Envelope, superusers: set[str] | frozenset[str]) -> bool:
    """判定事件发起者是否命中 SUPERUSERS。

    同时兼容三种配置写法：
    - 裸 ID（如 ``"3196373166"``）
    - 带平台前缀（如 ``"telegram:77001"`` / ``"qq:3196373166"``）
    - 完整 uni_id（如 ``"TelegramPlatform_Private_77001"``）
    """
    raw_uid = env.actor.user_id
    if not raw_uid:
        return False
    platform = env.actor.platform
    return (
        raw_uid in superusers
        or f"{platform}:{raw_uid}" in superusers
        or user_uni_id(platform, raw_uid) in superusers
    )
