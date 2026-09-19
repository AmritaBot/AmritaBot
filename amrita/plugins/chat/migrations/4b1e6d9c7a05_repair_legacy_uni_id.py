"""repair legacy uni_id

迁移 ID: 4b1e6d9c7a05
父迁移: c254b6952d47
创建时间: 2026-09-20 10:30:00.000000

把旧格式的会话 ID（``user_{id}`` / ``group_{id}``）改写为
``QQPlatform_Private_{id}`` / ``QQPlatform_Group_{id}``。

2ee162c4406c 已经做过同样的改写，但它在迁移图上位于 c254b6952d47 之前：
alembic_version 已经记录为 c254b6952d47 的数据库会把它当作已应用而跳过，
于是 1.8.0 运行期间新写入的旧格式记录不会被改写。这里在 c254b6952d47 之后
再执行一次，同时覆盖 2ee162c4406c 触及不到的上下文存储表
（amrita_chat_context_record / amrita_chat_context_media 的 uni_id）。

amrita_user_metadata.user_id 被其余三张表通过外键引用，且外键没有
ON UPDATE CASCADE，直接 UPDATE 会破坏引用关系；因此按
「插入新行 → 迁移子行 → 删除旧行」的顺序改写。目标 ID 已经存在时跳过该组，
避免唯一约束冲突或覆盖已有数据。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from nonebot import logger

revision: str = "4b1e6d9c7a05"
down_revision: str | Sequence[str] | None = "c254b6952d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#  父表，以及通过外键引用 user_id 的子表
_PARENT = "amrita_user_metadata"
_CHILDREN = ("amrita_memory_data", "amrita_memory_sessions", "amrita_group_config")
#  上下文存储按会话 ID 索引，没有外键
_CONTEXT_TABLES = ("amrita_chat_context_record", "amrita_chat_context_media")

_OLD_PATTERN = re.compile(r"^(user|group)_([0-9]+)$")
_NEW_PATTERN = re.compile(r"^QQPlatform_(Private|Group)_([0-9]+)$")


def _to_new(uni_id: str) -> str:
    """旧格式 → 推荐格式；其它格式原样返回（幂等）"""
    match = _OLD_PATTERN.match(uni_id)
    if not match:
        return uni_id
    extra = "Private" if match.group(1) == "user" else "Group"
    return f"QQPlatform_{extra}_{match.group(2)}"


def _to_old(uni_id: str) -> str:
    """推荐格式 → 旧格式；其它格式原样返回（幂等）"""
    match = _NEW_PATTERN.match(uni_id)
    if not match:
        return uni_id
    kind = "user" if match.group(1) == "Private" else "group"
    return f"{kind}_{match.group(2)}"


def _move_user_group(
    bind: sa.Connection, insp: sa.Inspector, pk_column: str | None, old: str, new: str
) -> None:
    """把 user_id=old 的一整组记录改写成 new，同时保持外键引用完整"""
    existing = bind.execute(
        sa.text(f"SELECT 1 FROM {_PARENT} WHERE user_id = :uid"), {"uid": new}
    ).first()
    if existing:
        #  目标 ID 已经被占用，保持原样，避免唯一约束冲突或覆盖已有数据
        logger.warning(
            f"{_PARENT} 中已存在 {new}，跳过 {old} 的 ID 改写，请手动合并这两条记录"
        )
        return

    quote = bind.dialect.identifier_preparer.quote
    columns = [
        column["name"]
        for column in insp.get_columns(_PARENT)
        if column["name"] != pk_column
    ]
    names = ", ".join(quote(column) for column in columns)
    values = ", ".join(
        ":new" if column == "user_id" else quote(column) for column in columns
    )
    bind.execute(
        sa.text(
            f"INSERT INTO {_PARENT} ({names}) "
            f"SELECT {values} FROM {_PARENT} WHERE user_id = :old"
        ),
        {"new": new, "old": old},
    )
    for child in _CHILDREN:
        if insp.has_table(child):
            bind.execute(
                sa.text(f"UPDATE {child} SET user_id = :new WHERE user_id = :old"),
                {"new": new, "old": old},
            )
    leftover = any(
        bind.execute(
            sa.text(f"SELECT 1 FROM {child} WHERE user_id = :old"), {"old": old}
        ).first()
        for child in _CHILDREN
        if insp.has_table(child)
    )
    if leftover:
        #  仍有子行指向旧 ID，保留旧行，否则 ondelete=CASCADE 会连带删除数据
        logger.warning(f"{old} 仍有子表记录未能改写，已保留原记录")
        return

    old_pk: object = None
    if pk_column is not None:
        old_pk = bind.execute(
            sa.text(f"SELECT {quote(pk_column)} FROM {_PARENT} WHERE user_id = :old"),
            {"old": old},
        ).scalar()
    bind.execute(sa.text(f"DELETE FROM {_PARENT} WHERE user_id = :old"), {"old": old})
    if pk_column is not None and old_pk is not None:
        #  沿用原来的主键值，避免依赖该列的外部引用失效
        bind.execute(
            sa.text(
                f"UPDATE {_PARENT} SET {quote(pk_column)} = :old_pk WHERE user_id = :new"
            ),
            {"old_pk": old_pk, "new": new},
        )


def _convert_column(
    bind: sa.Connection, table: str, column: str, convert: Callable[[str], str]
) -> None:
    """改写单张表里某个会话 ID 列（该列没有唯一约束与外键）"""
    quote = bind.dialect.identifier_preparer.quote
    rows = bind.execute(
        sa.text(f"SELECT {quote('id')}, {quote(column)} FROM {table}")
    ).fetchall()
    for row_id, uni_id in rows:
        new_id = convert(uni_id)
        if new_id != uni_id:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {quote(column)} = :new WHERE {quote('id')} = :row_id"
                ),
                {"new": new_id, "row_id": row_id},
            )


def _convert(bind: sa.Connection, convert: Callable[[str], str]) -> None:
    insp = sa.inspect(bind)
    if insp.has_table(_PARENT):
        pk_columns = insp.get_pk_constraint(_PARENT)["constrained_columns"] or []
        pk_column = pk_columns[0] if len(pk_columns) == 1 else None
        legacy_ids = (
            bind.execute(sa.text(f"SELECT user_id FROM {_PARENT}")).scalars().all()
        )
        for uni_id in legacy_ids:
            new_id = convert(uni_id)
            if new_id != uni_id:
                _move_user_group(bind, insp, pk_column, uni_id, new_id)
    for table in _CONTEXT_TABLES:
        if insp.has_table(table):
            _convert_column(bind, table, "uni_id", convert)


def upgrade(name: str = "") -> None:
    if name:
        return
    _convert(op.get_bind(), _to_new)


def downgrade(name: str = "") -> None:
    if name:
        return
    _convert(op.get_bind(), _to_old)
