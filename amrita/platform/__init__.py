"""平台抽象层：业务层只从这里取 DTO 与端口，具体实现留在各平台子包内。"""

from __future__ import annotations

from . import (
    identity,
    ingress,  # noqa: F401  导入即注册 event_preprocessor
    qq,  # noqa: F401  导入即注册 QQ 平台的适配器实现
    registry,
    telegram,  # noqa: F401  导入即注册 Telegram 平台的适配器实现
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
    "registry",
]
