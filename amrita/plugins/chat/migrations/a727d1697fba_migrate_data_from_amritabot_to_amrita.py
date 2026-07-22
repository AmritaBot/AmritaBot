"""migrate_data_from_amritabot_to_amrita

迁移 ID: a727d1697fba
父迁移: 072361e8936f
创建时间: 2026-07-21 19:52:57.319068

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a727d1697fba"
down_revision: str | Sequence[str] | None = "072361e8936f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _old_tables_exist() -> bool:
    """检查旧表 amritabot_* 是否存在（从零开始的 DB 没有这些表）"""
    inspector = sa.inspect(op.get_context().bind)
    assert inspector is not None
    return inspector.has_table("amritabot_user_metadata")


def _migrate_table_if_exists(src_table: str, dst_table: str, columns: str) -> None:
    """只在源表存在时执行 INSERT ... SELECT，否则静默跳过"""
    op.execute(
        f"INSERT OR IGNORE INTO {dst_table} ({columns}) "
        f"SELECT {columns} FROM {src_table} "
        f"WHERE EXISTS (SELECT 1 FROM sqlite_master "
        f"WHERE type='table' AND name='{src_table}')"
    )


def upgrade(name: str = "") -> None:
    if name:
        return

    old_exists = _old_tables_exist()

    if old_exists:
        # Step 0: 确保新表存在（降级后再升级时新表已被删除）
        op.execute(
            "CREATE TABLE IF NOT EXISTS amrita_global_insights ("
            " date VARCHAR(64) NOT NULL, "
            " token_input BIGINT NOT NULL DEFAULT 0, "
            " token_output BIGINT NOT NULL DEFAULT 0, "
            " usage_count INTEGER NOT NULL, "
            " PRIMARY KEY (date)"
            ")"
        )
        op.execute(
            "CREATE TABLE IF NOT EXISTS amrita_user_metadata ("
            " id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            " user_id VARCHAR(64) NOT NULL, "
            " last_active DATETIME NOT NULL, "
            " total_called_count BIGINT NOT NULL, "
            " total_input_token BIGINT NOT NULL, "
            " total_output_token BIGINT NOT NULL, "
            " tokens_input BIGINT NOT NULL, "
            " tokens_output BIGINT NOT NULL, "
            " called_count INTEGER NOT NULL, "
            " CONSTRAINT uq_amrita_user_metadata_user_id UNIQUE (user_id)"
            ")"
        )
        op.execute(
            "CREATE TABLE IF NOT EXISTS amrita_memory_data ("
            " id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            " user_id VARCHAR(64) NOT NULL, "
            " memory_json JSON NOT NULL DEFAULT '{}', "
            " extra_prompt TEXT NOT NULL, "
            " FOREIGN KEY(user_id) REFERENCES amrita_user_metadata(user_id) ON DELETE CASCADE, "
            " CONSTRAINT uq_amrita_memory_user_id UNIQUE (user_id)"
            ")"
        )
        op.execute(
            "CREATE TABLE IF NOT EXISTS amrita_memory_sessions ("
            " id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            " user_id VARCHAR(64) NOT NULL, "
            " created_at FLOAT NOT NULL, "
            " data JSON NOT NULL DEFAULT '{}', "
            " FOREIGN KEY(user_id) REFERENCES amrita_user_metadata(user_id) ON DELETE CASCADE"
            ")"
        )

        # Step 1: 从旧表拷贝数据到新表（跳过重复 key）
        # 每条 INSERT 内部检查旧表是否存在，兼容 clean-start 和已有数据两种场景
        _migrate_table_if_exists(
            "amritabot_global_insights",
            "amrita_global_insights",
            "date, token_input, token_output, usage_count",
        )
        _migrate_table_if_exists(
            "amritabot_user_metadata",
            "amrita_user_metadata",
            "id, user_id, last_active, total_called_count, total_input_token, "
            "total_output_token, tokens_input, tokens_output, called_count",
        )
        _migrate_table_if_exists(
            "amritabot_memory_data",
            "amrita_memory_data",
            "id, user_id, memory_json, extra_prompt",
        )
        _migrate_table_if_exists(
            "amritabot_memory_sessions",
            "amrita_memory_sessions",
            "id, user_id, created_at, data",
        )

        # Step 2: 修复 amrita_group_config 的外键引用
        with op.batch_alter_table("amrita_group_config", schema=None) as batch_op:
            batch_op.drop_constraint(
                batch_op.f("fk_amrita_group_config_user_id_amritabot_user_metadata"),
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                batch_op.f("fk_amrita_group_config_user_id_amrita_user_metadata"),
                "amrita_user_metadata",
                ["user_id"],
                ["user_id"],
                ondelete="CASCADE",
            )

        # Step 3: 删除旧表
        op.drop_table("amritabot_memory_sessions")
        op.drop_table("amritabot_memory_data")
        op.drop_table("amritabot_global_insights")
        op.drop_table("amritabot_user_metadata")

    # Step 4: 确保新表关键索引存在（IF NOT EXISTS，幂等）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_amrita_user_id_last_active "
        "ON amrita_user_metadata (user_id, last_active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_sessions_created_at_time "
        "ON amrita_memory_sessions (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_sessions_user_id "
        "ON amrita_memory_sessions (user_id)"
    )

    # ### end Alembic commands ###


def downgrade(name: str = "") -> None:
    if name:
        return

    # Step 1: 重建旧表（与 702651e6e3d8 中定义一致）
    op.create_table(
        "amritabot_user_metadata",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("last_active", sa.DateTime(), nullable=False),
        sa.Column("total_called_count", sa.BigInteger(), nullable=False),
        sa.Column("total_input_token", sa.BigInteger(), nullable=False),
        sa.Column("total_output_token", sa.BigInteger(), nullable=False),
        sa.Column("tokens_input", sa.BigInteger(), nullable=False),
        sa.Column("tokens_output", sa.BigInteger(), nullable=False),
        sa.Column("called_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_amritabot_user_metadata")),
        sa.UniqueConstraint("user_id", name="uq_amrita_user_metadata_user_id"),
    )

    op.create_table(
        "amritabot_memory_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "memory_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("extra_prompt", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["amritabot_user_metadata.user_id"],
            name=op.f("fk_amritabot_memory_data_user_id_amritabot_user_metadata"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_amritabot_memory_data")),
        sa.UniqueConstraint("user_id", name="uq_amrita_memory_user_id"),
    )

    op.create_table(
        "amritabot_memory_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["amritabot_user_metadata.user_id"],
            name=op.f("fk_amritabot_memory_sessions_user_id_amritabot_user_metadata"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_amritabot_memory_sessions")),
    )

    op.create_table(
        "amritabot_global_insights",
        sa.Column("date", sa.String(length=64), nullable=False),
        sa.Column(
            "token_input",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "token_output",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_amritabot_global_insights")),
    )

    # Step 2: 从新表回拷数据到旧表
    op.execute(
        "INSERT INTO amritabot_global_insights SELECT * FROM amrita_global_insights"
    )
    op.execute("INSERT INTO amritabot_user_metadata SELECT * FROM amrita_user_metadata")
    op.execute("INSERT INTO amritabot_memory_data SELECT * FROM amrita_memory_data")
    op.execute(
        "INSERT INTO amritabot_memory_sessions SELECT * FROM amrita_memory_sessions"
    )

    # Step 3: 还原 amrita_group_config 的外键引用
    with op.batch_alter_table("amrita_group_config", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_amrita_group_config_user_id_amrita_user_metadata"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_amrita_group_config_user_id_amritabot_user_metadata"),
            "amritabot_user_metadata",
            ["user_id"],
            ["user_id"],
            ondelete="CASCADE",
        )

    # Step 4: 删除新表
    op.execute("DROP INDEX IF EXISTS idx_am_sessions_user_id")
    op.execute("DROP INDEX IF EXISTS idx_am_sessions_created_at_time")
    op.drop_table("amrita_memory_sessions")
    op.drop_table("amrita_memory_data")
    op.execute("DROP INDEX IF EXISTS idx_amrita_user_id_last_active")
    op.drop_table("amrita_user_metadata")
    op.drop_table("amrita_global_insights")
