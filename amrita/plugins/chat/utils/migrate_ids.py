"""旧 ID 格式迁移工具（纯函数，不触碰数据库 / alembic）

旧格式：``user_{qq}`` / ``group_{群号}``
新格式（README 推荐）：``QQPlatform_Private_{qq}`` / ``QQPlatform_Group_{群号}``
（QQ 系平台统一为 QQPlatform，与 ``utils.uni.uni_target_id`` 归并规则一致）

本文件不注册任何自动执行逻辑。
"""

from __future__ import annotations

import re

_OLD_PATTERN = re.compile(r"^(user|group)_([0-9]+)$")
_NEW_PATTERN = re.compile(r"^QQPlatform_(Private|Group)_([0-9]+)$")


def is_old_format(uni_id: str) -> bool:
    """判断是否为旧格式（user_ / group_ 前缀）"""
    return bool(_OLD_PATTERN.match(uni_id))


def is_new_format(uni_id: str) -> bool:
    """判断是否为推荐格式（AdapterType_ExtraType_UserPayload）"""
    return bool(_NEW_PATTERN.match(uni_id))


def transform_old_to_new(uni_id: str) -> str:
    """旧格式 → 推荐格式；非旧格式原样返回（幂等）"""
    match = _OLD_PATTERN.match(uni_id)
    if not match:
        return uni_id
    kind, payload = match.group(1), match.group(2)
    extra = "Private" if kind == "user" else "Group"
    return f"QQPlatform_{extra}_{payload}"


def transform_new_to_old(uni_id: str) -> str | None:
    """推荐格式 → 旧格式（迁移回滚用）；非新格式返回 None"""
    match = _NEW_PATTERN.match(uni_id)
    if not match:
        return None
    kind, payload = match.group(1), match.group(2)
    return f"{'user' if kind == 'Private' else 'group'}_{payload}"
