"""平台抽象层：业务层只从这里取 DTO 与端口，具体实现由命名空间扫描注册。"""

from __future__ import annotations

import sys

from amrita_core.utils import side_effect_import

from . import identity, registry
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

for _item in side_effect_import(sys.modules[__name__], False):
    if isinstance(_item, BaseException):
        # 单个平台实现导入失败不该拖垮整个框架，缺哪个平台由 registry 的空列表体现
        registry.log_import_failure(_item)

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
