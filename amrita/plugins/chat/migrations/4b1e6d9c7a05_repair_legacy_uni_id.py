"""repair legacy uni_id

迁移 ID: 4b1e6d9c7a05
父迁移: c254b6952d47
创建时间: 2026-09-20 10:30:00.000000

把旧格式的会话 ID（``user_{id}`` / ``group_{id}``）改写为
``QQPlatform_Private_{id}`` / ``QQPlatform_Group_{id}``。

本迁移是 head，任何数据库升级时都必然执行且只执行一次，因此全部改写逻辑都
集中在这里，2ee162c4406c 只保留 revision 骨架、不做任何数据操作。

涉及的表：

* amrita_user_metadata / amrita_memory_data / amrita_memory_sessions /
  amrita_group_config —— 都带 user_id 列，且后三张表通过外键引用第一张表。
  外键只有 ON DELETE CASCADE、没有 ON UPDATE CASCADE，就地 UPDATE 会破坏
  引用关系，因此采用临时表方案重建这四张表。
* amrita_chat_context_record / amrita_chat_context_media —— uni_id 列，
  没有外键，可以直接在原表上改写。
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

_PARENT = "amrita_user_metadata"
_TMP_SUFFIX = "_uni_id_tmp"

#  (表名, 唯一约束名, 外键约束名, 索引)
_TableSpec = tuple[str, str | None, str | None, list[tuple[str, list[str]]]]
_TABLE_SPECS: list[_TableSpec] = [
    (
        "amrita_user_metadata",
        "uq_amrita_user_metadata_user_id",
        None,
        [("idx_amrita_user_id_last_active", ["user_id", "last_active"])],
    ),
    (
        "amrita_memory_data",
        "uq_amrita_memory_user_id",
        "fk_amrita_memory_data_uid",
        [],
    ),
    (
        "amrita_memory_sessions",
        None,
        "fk_amrita_memory_sessions_uid",
        [
            ("idx_am_sessions_user_id", ["user_id"]),
            ("idx_am_sessions_created_at_time", ["created_at"]),
        ],
    ),
    (
        "amrita_group_config",
        "uq_amrita_group_config_user_id",
        "fk_amrita_group_config_uid",
        [("idx_amrita_group_config_user_id", ["user_id"])],
    ),
]

#  上下文存储按会话 ID 索引，没有外键，可以就地改写
_CONTEXT_COLUMNS: list[tuple[str, str]] = [
    ("amrita_chat_context_record", "uni_id"),
    ("amrita_chat_context_media", "uni_id"),
]

_OLD_PATTERN = re.compile(r"^(user|group)_([0-9]+)$")
_NEW_PATTERN = re.compile(r"^QQPlatform_(Private|Group)_([0-9]+)$")


def _spec_of(table: str) -> _TableSpec:
    return next(spec for spec in _TABLE_SPECS if spec[0] == table)


def _id_columns() -> list[tuple[str, str]]:
    """所有需要改写的 (表名, 会话 ID 列)"""
    return [(spec[0], "user_id") for spec in _TABLE_SPECS] + list(_CONTEXT_COLUMNS)


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


#  列定义。Column 对象不能跨表复用，因此每次调用都新建一份
def _user_metadata_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("last_active", sa.DateTime(), nullable=False),
        sa.Column("total_called_count", sa.BigInteger(), nullable=False),
        sa.Column("total_input_token", sa.BigInteger(), nullable=False),
        sa.Column("total_output_token", sa.BigInteger(), nullable=False),
        sa.Column("tokens_input", sa.BigInteger(), nullable=False),
        sa.Column("tokens_output", sa.BigInteger(), nullable=False),
        sa.Column("called_count", sa.Integer(), nullable=False),
    ]


def _memory_data_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "memory_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("extra_prompt", sa.Text(), nullable=False),
    ]


def _memory_sessions_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    ]


def _group_config_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("enable", sa.Boolean(), nullable=False),
        sa.Column("autoreply", sa.Boolean(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
    ]


_COLUMNS: dict[str, Callable[[], list[sa.Column]]] = {
    "amrita_user_metadata": _user_metadata_columns,
    "amrita_memory_data": _memory_data_columns,
    "amrita_memory_sessions": _memory_sessions_columns,
    "amrita_group_config": _group_config_columns,
}


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _quote(*names: str) -> str:
    """按当前方言引用标识符（MySQL 用反引号，其余用双引号）"""
    quote = op.get_bind().dialect.identifier_preparer.quote
    return ", ".join(quote(name) for name in names)


def _tmp_name(table: str) -> str:
    return f"_{table}{_TMP_SUFFIX}"


def _create_table(
    spec: _TableSpec, table_name: str, *, temporary: bool = False
) -> None:
    """按定义建表；临时表不带外键，约束名加后缀避免与正式表重名"""
    table, unique_name, foreign_key_name, _ = spec
    constraints: list[sa.schema.SchemaItem] = []
    if foreign_key_name is not None and not temporary:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["user_id"],
                [f"{_PARENT}.user_id"],
                name=foreign_key_name,
                ondelete="CASCADE",
            )
        )
    constraints.append(sa.PrimaryKeyConstraint("id"))
    if unique_name is not None:
        constraints.append(
            sa.UniqueConstraint(
                "user_id",
                name=f"{unique_name}{_TMP_SUFFIX}" if temporary else unique_name,
            )
        )
    op.create_table(table_name, *_COLUMNS[table](), *constraints)


def _copy(src: str, dst: str, columns: list[str]) -> None:
    """整表拷贝交给数据库执行，避免把 JSON 等列取回 Python 侧"""
    names = _quote(*columns)
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_quote(dst)} ({names}) SELECT {names} FROM {_quote(src)}"
        )
    )


def _build_mapping(
    convert: Callable[[str], str],
    candidates: list[tuple[str, str]],
    occupied: list[str],
) -> dict[str, str]:
    """计算需要改写的 ID 对；目标 ID 已被占用时跳过，避免唯一约束冲突"""
    bind = op.get_bind()
    occupied_ids = {
        table: set(
            bind.execute(sa.text(f"SELECT user_id FROM {_quote(table)}")).scalars()
        )
        for table in occupied
    }
    known: set[str] = set()
    for table, column in candidates:
        known.update(
            bind.execute(
                sa.text(f"SELECT {_quote(column)} FROM {_quote(table)}")
            ).scalars()
        )

    mapping: dict[str, str] = {}
    for uni_id in sorted(known):
        new_id = convert(uni_id)
        if new_id == uni_id:
            continue
        taken = [table for table, ids in occupied_ids.items() if new_id in ids]
        if taken:
            logger.warning(
                f"{'、'.join(taken)} 中已存在 {new_id}，跳过 {uni_id} 的 ID 改写"
            )
            continue
        mapping[uni_id] = new_id
    return mapping


def _sync_sequence(table: str) -> None:
    """PostgreSQL 显式写入主键不会推进序列，重建后需要手动对齐"""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        sa.text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE(MAX(id), 0) + 1, false) FROM {_quote(table)}"
        )
    )


def _rebuild(present: list[_TableSpec], mapping: dict[str, str]) -> None:
    if not present:
        return
    tables = [spec[0] for spec in present]
    columns = {table: [column.name for column in _COLUMNS[table]()] for table in tables}

    #  1. 建临时表（不带外键）并整体拷贝数据
    for table in tables:
        tmp = _tmp_name(table)
        if _inspector().has_table(tmp):
            op.drop_table(tmp)
        _create_table(_spec_of(table), tmp, temporary=True)
        _copy(table, tmp, columns[table])

    #  2. 在临时表内改写 user_id，此处没有外键约束
    user_id = _quote("user_id")
    for table in tables:
        tmp = _quote(_tmp_name(table))
        for old, new in mapping.items():
            op.get_bind().execute(
                sa.text(f"UPDATE {tmp} SET {user_id} = :new WHERE {user_id} = :old"),
                {"new": new, "old": old},
            )

    #  3. 删除旧表（先删引用方，最后删被引用方）
    for table in reversed(tables):
        op.drop_table(table)

    #  4. 按原定义重建（带外键与索引）
    for table in tables:
        _create_table(_spec_of(table), table)
        for index_name, index_columns in _spec_of(table)[3]:
            op.create_index(index_name, table, index_columns)

    #  5. 数据拷回
    for table in tables:
        _copy(_tmp_name(table), table, columns[table])

    #  6. 删除临时表
    for table in tables:
        op.drop_table(_tmp_name(table))

    #  7. 对齐自增序列
    for table in tables:
        _sync_sequence(table)


def _convert_context(mapping: dict[str, str]) -> None:
    """上下文存储没有外键与唯一约束，直接在原表上改写"""
    if not mapping:
        return
    insp = _inspector()
    bind = op.get_bind()
    for table, column in _CONTEXT_COLUMNS:
        if not insp.has_table(table):
            continue
        quoted_column = _quote(column)
        for old, new in mapping.items():
            bind.execute(
                sa.text(
                    f"UPDATE {_quote(table)} SET {quoted_column} = :new "
                    f"WHERE {quoted_column} = :old"
                ),
                {"new": new, "old": old},
            )


def _rewrite(convert: Callable[[str], str]) -> None:
    insp = _inspector()
    candidates = [
        (table, column) for table, column in _id_columns() if insp.has_table(table)
    ]
    if not candidates:
        return
    present = [spec for spec in _TABLE_SPECS if insp.has_table(spec[0])]
    mapping = _build_mapping(convert, candidates, [spec[0] for spec in present])
    _rebuild(present, mapping)
    _convert_context(mapping)


def upgrade(name: str = "") -> None:
    if name:
        return
    _rewrite(_to_new)


def downgrade(name: str = "") -> None:
    if name:
        return
    _rewrite(_to_old)
