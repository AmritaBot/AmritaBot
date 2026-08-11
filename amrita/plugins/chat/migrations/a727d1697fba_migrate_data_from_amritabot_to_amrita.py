"""migrate_data_from_amritabot_to_amrita

迁移 ID: a727d1697fba
父迁移: 072361e8936f
创建时间: 2026-07-21 19:52:57.319068
修复时间: 2026-07-23 10:10:39.149909

将 amritabot_* 旧表数据迁移到 amrita_* 新表。
group_config 通过新建替换实现 FK 无缝切换。
*补充：修复了索引问题
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a727d1697fba"
down_revision: str | Sequence[str] | None = "072361e8936f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "702651e6e3d8"

#  列定义
_GLOBAL_INSIGHTS_COLS = [
    sa.Column("date", sa.String(64), nullable=False),
    sa.Column(
        "token_input", sa.BigInteger(), server_default=sa.text("0"), nullable=False
    ),
    sa.Column(
        "token_output", sa.BigInteger(), server_default=sa.text("0"), nullable=False
    ),
    sa.Column("usage_count", sa.Integer(), nullable=False),
]
_USER_METADATA_COLS = [
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
_MEMORY_DATA_COLS = [
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("memory_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    sa.Column("extra_prompt", sa.Text(), nullable=False),
]
_MEMORY_SESSIONS_COLS = [
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.Float(), nullable=False),
    sa.Column("data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
]
_GROUP_CONFIG_COLS = [
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("enable", sa.Boolean(), nullable=False),
    sa.Column("autoreply", sa.Boolean(), nullable=False),
    sa.Column("last_updated", sa.DateTime(), nullable=False),
]

_GROUP_CONFIG_COL_NAMES = ["id", "user_id", "enable", "autoreply", "last_updated"]

# (旧表, 新表, 列定义, 列名)
_MIGRATION_TABLES: list[tuple[str, str, list[sa.Column], list[str]]] = [
    (
        "amritabot_global_insights",
        "amrita_global_insights",
        _GLOBAL_INSIGHTS_COLS,
        ["date", "token_input", "token_output", "usage_count"],
    ),
    (
        "amritabot_user_metadata",
        "amrita_user_metadata",
        _USER_METADATA_COLS,
        [
            "id",
            "user_id",
            "last_active",
            "total_called_count",
            "total_input_token",
            "total_output_token",
            "tokens_input",
            "tokens_output",
            "called_count",
        ],
    ),
    (
        "amritabot_memory_data",
        "amrita_memory_data",
        _MEMORY_DATA_COLS,
        ["id", "user_id", "memory_json", "extra_prompt"],
    ),
    (
        "amritabot_memory_sessions",
        "amrita_memory_sessions",
        _MEMORY_SESSIONS_COLS,
        ["id", "user_id", "created_at", "data"],
    ),
]


#  辅助
def _inspector():
    insp = sa.inspect(op.get_bind())
    assert insp is not None
    return insp


def _old_tables_exist() -> bool:
    return _inspector().has_table("amritabot_user_metadata")


def _table(name: str, cols: list[str]) -> sa.sql.expression.TableClause:
    return sa.table(name, *[sa.column(c) for c in cols])


def _copy_table(src_name: str, dst_name: str, col_names: list[str]) -> None:
    """逐行拷贝，按第一列（主键）去重。"""
    if not _inspector().has_table(src_name):
        return
    pk_col = col_names[0]
    dst = _table(dst_name, col_names)
    src = _table(src_name, col_names)
    sel = sa.select(src).where(
        ~sa.exists(sa.select(1).select_from(dst).where(dst.c[pk_col] == src.c[pk_col]))
    )
    op.execute(dst.insert().from_select(col_names, sel))


def _ensure_indexes() -> None:
    """确保关键索引存在（幂等），覆盖 clean-start 和完整迁移两种路径。"""
    _INDICES: list[tuple[str, str, list[str]]] = [
        (
            "idx_amrita_user_id_last_active",
            "amrita_user_metadata",
            ["user_id", "last_active"],
        ),
        ("idx_am_sessions_user_id", "amrita_memory_sessions", ["user_id"]),
        (
            "idx_am_sessions_created_at_time",
            "amrita_memory_sessions",
            ["created_at"],
        ),
    ]
    for idx_name, table_name, cols in _INDICES:
        insp = _inspector()
        if not insp.has_table(table_name):
            continue
        existing = {i["name"] for i in insp.get_indexes(table_name)}
        if idx_name not in existing:
            op.create_index(idx_name, table_name, cols)


#  upgrade
def upgrade(name: str = "") -> None:

    if not _old_tables_exist():
        _ensure_indexes()
        return

    # ── 有旧表 ──

    # 1. 创建新表（不带 GroupConfig），FK 引用 amrita_user_metadata
    insp = _inspector()
    if not insp.has_table("amrita_global_insights"):
        op.create_table(
            "amrita_global_insights",
            *_GLOBAL_INSIGHTS_COLS,
            sa.PrimaryKeyConstraint("date"),
        )
    if not insp.has_table("amrita_user_metadata"):
        op.create_table(
            "amrita_user_metadata",
            *_USER_METADATA_COLS,
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_amrita_user_metadata_user_id"),
            sa.Index("idx_amrita_user_id_last_active", "user_id", "last_active"),
        )
    if not insp.has_table("amrita_memory_data"):
        op.create_table(
            "amrita_memory_data",
            *_MEMORY_DATA_COLS,
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["amrita_user_metadata.user_id"],
                name="fk_amrita_memory_data_uid",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_amrita_memory_user_id"),
        )
    if not insp.has_table("amrita_memory_sessions"):
        op.create_table(
            "amrita_memory_sessions",
            *_MEMORY_SESSIONS_COLS,
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["amrita_user_metadata.user_id"],
                name="fk_amrita_memory_sessions_uid",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.Index("idx_am_sessions_user_id", "user_id"),
            sa.Index("idx_am_sessions_created_at_time", "created_at"),
        )

    # 2. 创建 GROUP_CONFIG 临时表（无 FK）
    _TMP = "_amrita_group_config_tmp"
    if not insp.has_table(_TMP):
        op.create_table(
            _TMP,
            *_GROUP_CONFIG_COLS,
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name=f"uq_{_TMP}_uid"),
        )

    # 3. 数据逐条迁移
    _copy_table(
        "amritabot_global_insights",
        "amrita_global_insights",
        ["date", "token_input", "token_output", "usage_count"],
    )
    _copy_table(
        "amritabot_user_metadata",
        "amrita_user_metadata",
        [
            "id",
            "user_id",
            "last_active",
            "total_called_count",
            "total_input_token",
            "total_output_token",
            "tokens_input",
            "tokens_output",
            "called_count",
        ],
    )
    _copy_table(
        "amritabot_memory_data",
        "amrita_memory_data",
        ["id", "user_id", "memory_json", "extra_prompt"],
    )
    _copy_table(
        "amritabot_memory_sessions",
        "amrita_memory_sessions",
        ["id", "user_id", "created_at", "data"],
    )
    _copy_table("amrita_group_config", _TMP, _GROUP_CONFIG_COL_NAMES)

    # 4. 全量删除旧表（先删依赖方，最后删被依赖方）
    for tbl in [
        "amritabot_memory_sessions",
        "amritabot_memory_data",
        "amritabot_global_insights",
        "amrita_group_config",
        "amritabot_user_metadata",
    ]:
        if _inspector().has_table(tbl):
            op.drop_table(tbl)

    # 5. 创建新 GROUP_CONFIG（FK -> amrita_user_metadata）
    op.create_table(
        "amrita_group_config",
        *_GROUP_CONFIG_COLS,
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["amrita_user_metadata.user_id"],
            name="fk_amrita_group_config_uid",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_amrita_group_config_user_id"),
        sa.Index("idx_amrita_group_config_user_id", "user_id"),
    )

    # 6. GROUP_CONFIG 数据迁移
    _copy_table(_TMP, "amrita_group_config", _GROUP_CONFIG_COL_NAMES)

    # 7. 移除临时表
    op.drop_table(_TMP)

    # 8. 兜底：确保索引存在（覆盖表已有但索引缺失的边缘情况）
    _ensure_indexes()


#  downgrade
def downgrade(name: str = "") -> None:

    insp = _inspector()

    # 1. 重建旧表
    if not insp.has_table("amritabot_user_metadata"):
        op.create_table(
            "amritabot_user_metadata",
            *_USER_METADATA_COLS,
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_amrita_user_metadata_user_id"),
        )
    if not insp.has_table("amritabot_memory_data"):
        op.create_table(
            "amritabot_memory_data",
            *_MEMORY_DATA_COLS,
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["amritabot_user_metadata.user_id"],
                name="fk_amritabot_mem_data_uid",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_amrita_memory_user_id"),
        )
    if not insp.has_table("amritabot_memory_sessions"):
        op.create_table(
            "amritabot_memory_sessions",
            *_MEMORY_SESSIONS_COLS,
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["amritabot_user_metadata.user_id"],
                name="fk_amritabot_mem_sessions_uid",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if not insp.has_table("amritabot_global_insights"):
        op.create_table(
            "amritabot_global_insights",
            *_GLOBAL_INSIGHTS_COLS,
            sa.PrimaryKeyConstraint("date"),
        )

    # 2. GROUP_CONFIG 临时表（无 FK）
    _TMP = "_amrita_group_config_tmp"
    if not insp.has_table(_TMP):
        op.create_table(
            _TMP,
            *_GROUP_CONFIG_COLS,
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name=f"uq_{_TMP}_uid"),
        )

    # 3. 回拷数据（新 -> 旧）
    for src_old, dst_new, _cols, col_names in _MIGRATION_TABLES:
        src_table, dst_table = dst_new, src_old
        if insp.has_table(src_table):
            st_src = _table(src_table, col_names)
            st_dst = _table(dst_table, col_names)
            op.execute(st_dst.insert().from_select(col_names, sa.select(st_src)))

    _copy_table("amrita_group_config", _TMP, _GROUP_CONFIG_COL_NAMES)

    # 4. 全量删除新表
    for tbl in [
        "amrita_memory_sessions",
        "amrita_memory_data",
        "amrita_group_config",
        "amrita_global_insights",
        "amrita_user_metadata",
    ]:
        if insp.has_table(tbl):
            op.drop_table(tbl)

    # 5. 重建旧 GROUP_CONFIG（FK -> amritabot_user_metadata）
    op.create_table(
        "amrita_group_config",
        *_GROUP_CONFIG_COLS,
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["amritabot_user_metadata.user_id"],
            name="fk_amrita_group_config_uid",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_amrita_group_config_user_id"),
        sa.Index("idx_amrita_group_config_user_id", "user_id"),
    )

    # 6. 回迁 GROUP_CONFIG 数据
    _copy_table(_TMP, "amrita_group_config", _GROUP_CONFIG_COL_NAMES)

    # 7. 清理临时表
    op.drop_table(_TMP)
