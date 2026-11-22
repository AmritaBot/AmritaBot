"""会话身份与 uni_id 映射。

``uni_id`` 是记忆、权限、黑名单的主键，格式必须与
``amrita.plugins.chat.utils.sql.make_uni_id`` 逐字节一致：

    QQPlatform_Group_{群号}
    QQPlatform_Private_{QQ号}

这里不 import 那个模块，避免 platform 层反向依赖业务层；
一致性由 ``tests/platform/test_platform.py`` 的对拍用例守住。
"""

from __future__ import annotations

import re

from .dto import CHANNEL, GROUP, Scope

QQ_ADAPTER_NAME = "QQPlatform"
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
    return f"{QQ_ADAPTER_NAME}_{extra}_{scope.id}"


def parse_uni_id(value: str) -> Scope | None:
    """主键 → Scope（platform 名统一按 qq 处理）。"""
    if not isinstance(value, str):
        return None
    if match := _UNI_ID_PATTERN.match(value):
        extra, payload = match.group(1), match.group(2)
        return Scope(
            platform="qq",
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
    return f"{QQ_ADAPTER_NAME}_{_EXTRA_PRIVATE}_{user_id}"


def thread_uni_id(scope: Scope) -> str:
    """带二级会话（话题/子区）的显式分桶键。

    刻意不并入 :func:`uni_id`：现有记忆、权限、黑名单都以 uni_id 为主键，
    把 thread 拼进去会让所有历史记录在切版当天变成孤儿。
    需要在话题维度隔离的场景（如 Telegram forum topic）显式调用这个函数。
    """
    base = uni_id(scope)
    return f"{base}#{scope.thread}" if scope.thread else base
