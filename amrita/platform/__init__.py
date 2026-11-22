"""platform 抽象层。

业务层（plugins/*）只允许从这里取 :mod:`dto`、:mod:`ports`、:mod:`registry`、:mod:`identity`，
具体适配器实现只在 ``amrita/platform/qq/`` 内部出现。
"""

from __future__ import annotations

from . import (
    identity,
    qq,  # noqa: F401  导入即注册 QQ 平台的适配器实现
    registry,
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
