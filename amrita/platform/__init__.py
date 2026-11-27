"""平台抽象层：业务层只从这里取 DTO 与端口，实现放在 impl 命名空间里按需加载。"""

from __future__ import annotations

from . import identity, registry
from .di import EnvelopeNBDep, OptionalEnvelopeNBDep
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
from .loader import load_ports

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
    "OptionalEnvelopeNBDep",
    "Part",
    "Scope",
    "identity",
    "load_ports",
    "registry",
]
