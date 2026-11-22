"""平台无关的公共小工具：角色归一化与去重键。"""

from __future__ import annotations

from .dto import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_SYSTEM,
    MetaScalar,
)


def normalize_role(role: str | None) -> str:
    """平台角色字面量 → 统一角色，未知含 Telegram 的 restricted/left/kicked 一律降级 member。"""
    if not isinstance(role, str):
        return ROLE_MEMBER
    match role.lower():
        case "owner" | "creator":
            return ROLE_OWNER
        case "admin" | "administrator":
            return ROLE_ADMIN
        case "system" | "bot":
            return ROLE_SYSTEM
        case _:
            return ROLE_MEMBER


def dedupe_key(platform: str, kind: str, *pieces: MetaScalar) -> str:
    """拼接去重键；空片段保留占位，避免相邻字段错位后撞键。"""
    body = ":".join("" if piece is None else str(piece) for piece in pieces)
    return f"{platform}:{kind}:{body}"


__all__ = ["dedupe_key", "normalize_role"]
