"""qqplatform_user_id

迁移 ID: 2ee162c4406c
父迁移: a727d1697fba

将会话 ID 从旧格式（user_{id} / group_{id}）迁移到推荐格式
（QQPlatform_Private_{id} / QQPlatform_Group_{id}），对齐
nonebot_plugin_amrita README 的 AdapterType_ExtraType_UserPayload 规范。

涉及表：amrita_user_metadata / amrita_memory_data / amrita_memory_sessions /
amrita_group_config（均含 user_id 列，前两者通过 FK 关联 user_metadata）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2ee162c4406c"
down_revision: str | Sequence[str] | None = "a727d1697fba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "amrita_user_metadata",
    "amrita_memory_data",
    "amrita_memory_sessions",
    "amrita_group_config",
)

_OLD_PATTERN = re.compile(r"^(user|group)_([0-9]+)$")
_NEW_PATTERN = re.compile(r"^QQPlatform_(Private|Group)_([0-9]+)$")


def _to_new(uni_id: str) -> str:
    """旧格式 → 推荐格式；非旧格式原样返回（幂等）"""
    match = _OLD_PATTERN.match(uni_id)
    if not match:
        return uni_id
    kind, payload = match.group(1), match.group(2)
    extra = "Private" if kind == "user" else "Group"
    return f"QQPlatform_{extra}_{payload}"


def _to_old(uni_id: str) -> str | None:
    """推荐格式 → 旧格式（回滚）；非新格式返回 None"""
    match = _NEW_PATTERN.match(uni_id)
    if not match:
        return None
    kind, payload = match.group(1), match.group(2)
    return f"{'user' if kind == 'Private' else 'group'}_{payload}"


def _rewrite(uni_id: str, forward: bool) -> str:
    return _to_new(uni_id) if forward else (_to_old(uni_id) or uni_id)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if not sa.inspect(bind).has_table(table):
            continue
        rows = bind.execute(sa.text(f"SELECT id, user_id FROM {table}")).fetchall()
        for rid, uid in rows:
            new_id = _rewrite(uid, forward=True)
            if new_id != uid:
                bind.execute(
                    sa.text(f"UPDATE {table} SET user_id = :n WHERE id = :i"),
                    {"n": new_id, "i": rid},
                )


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if not sa.inspect(bind).has_table(table):
            continue
        rows = bind.execute(sa.text(f"SELECT id, user_id FROM {table}")).fetchall()
        for rid, uid in rows:
            old_id = _rewrite(uid, forward=False)
            if old_id != uid:
                bind.execute(
                    sa.text(f"UPDATE {table} SET user_id = :n WHERE id = :i"),
                    {"n": old_id, "i": rid},
                )
