"""平台抽象层：业务层只从这里取 DTO 与端口，具体实现留在各平台子包内。"""

from __future__ import annotations

from . import (
    identity,
    ingress,
    qq,
    registry,
    telegram,
)
from .di import EnvelopeNBDep
from .dto import (
    GROUP,
    MESSAGE,
    META,
    NOTICE,
    PRIVATE,
    REQUEST,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_SYSTEM,
    UNKNOWN,
    Actor,
    Envelope,
    Part,
    Scope,
)

__all__ = [
    "GROUP",
    "MESSAGE",
    "META",
    "NOTICE",
    "PRIVATE",
    "REQUEST",
    "ROLE_ADMIN",
    "ROLE_MEMBER",
    "ROLE_OWNER",
    "ROLE_SYSTEM",
    "UNKNOWN",
    "Actor",
    "Envelope",
    "EnvelopeNBDep",
    "Part",
    "Scope",
    "identity",
    "ingress",
    "qq",
    "registry",
    "telegram",
]
