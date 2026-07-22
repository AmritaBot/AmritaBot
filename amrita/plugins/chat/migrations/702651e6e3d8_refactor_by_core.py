"""refactor_by_core

迁移 ID: 702651e6e3d8
父迁移: b54b093a9ce3
创建时间: 2026-02-18 11:44:46.427672

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

revision: str = "702651e6e3d8"
down_revision: str | Sequence[str] | None = "b54b093a9ce3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def table_exists(table_name: str) -> bool:
    """检查表是否已存在"""
    # 获取当前连接
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    return inspector.has_table(table_name)


def safe_drop_constraint(
    batch_op, constraint_name: str, type_: str = "foreignkey"
) -> None:
    """安全删除约束，仅忽略不存在的约束错误"""
    try:
        batch_op.drop_constraint(batch_op.f(constraint_name), type_=type_)
    except Exception as e:
        error_msg = str(e).lower()
        if (
            "not found" in error_msg
            or "doesn't exist" in error_msg
            or "no constraint" in error_msg
        ):
            pass
        else:
            # 其他错误，重新抛出
            raise


def safe_drop_index(batch_op, index_name: str) -> None:
    """安全删除索引，仅忽略不存在的索引错误"""
    try:
        batch_op.drop_index(batch_op.f(index_name))
    except Exception as e:
        # 检查是否是索引不存在的错误，如果是则忽略
        error_msg = str(e).lower()
        if (
            "not found" in error_msg
            or "doesn't exist" in error_msg
            or "no index" in error_msg
        ):
            # 索引不存在，这是预期情况，忽略
            pass
        else:
            # 其他错误，重新抛出
            raise


def upgrade(name: str = "") -> None:
    if name:
        return

    # 创建新表，如果已存在则跳过
    if not table_exists("amritabot_global_insights"):
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
            info={"bind_key": "chat"},
        )

    if not table_exists("amritabot_user_metadata"):
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
            info={"bind_key": "chat"},
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_amrita_user_id_last_active "
            "ON amritabot_user_metadata (user_id, last_active)"
        )

    if not table_exists("amrita_group_config"):
        op.create_table(
            "amrita_group_config",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("enable", sa.Boolean(), nullable=False),
            sa.Column("autoreply", sa.Boolean(), nullable=False),
            sa.Column("last_updated", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["amritabot_user_metadata.user_id"],
                name=op.f("fk_amrita_group_config_user_id_amritabot_user_metadata"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_amrita_group_config")),
            sa.UniqueConstraint("user_id", name="uq_amrita_group_config_user_id"),
            info={"bind_key": "chat"},
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_amrita_group_config_user_id "
            "ON amrita_group_config (user_id)"
        )

    if not table_exists("amritabot_memory_data"):
        op.create_table(
            "amritabot_memory_data",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column(
                "memory_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False
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
            info={"bind_key": "chat"},
        )

    if not table_exists("amritabot_memory_sessions"):
        op.create_table(
            "amritabot_memory_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column(
                "data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["amritabot_user_metadata.user_id"],
                name=op.f(
                    "fk_amritabot_memory_sessions_user_id_amritabot_user_metadata"
                ),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_amritabot_memory_sessions")),
            info={"bind_key": "chat"},
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_created_at_time "
            "ON amritabot_memory_sessions (created_at)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id "
            "ON amritabot_memory_sessions (user_id)"
        )

    # 处理旧表，只有当它们存在时才删除
    if table_exists("suggarchat_memory_sessions"):
        with op.batch_alter_table(
            "suggarchat_memory_sessions", schema=None
        ) as batch_op:
            # 先删除外键约束
            safe_drop_constraint(
                batch_op,
                "fk_suggarchat_memory_sessions_ins_id_suggarchat_memory_data",
                type_="foreignkey",
            )
            safe_drop_constraint(
                batch_op,
                "fk_suggarchat_memory_sessions_is_group_suggarchat_memory_data",
                type_="foreignkey",
            )

            # 删除索引
            safe_drop_index(batch_op, "idx_sessions_created_at")
            safe_drop_index(batch_op, "idx_sessions_ins_id")
            safe_drop_index(batch_op, "idx_sessions_is_group")

        op.drop_table("suggarchat_memory_sessions")

    if table_exists("suggarchat_group_config"):
        with op.batch_alter_table("suggarchat_group_config", schema=None) as batch_op:
            safe_drop_constraint(
                batch_op,
                "fk_suggarchat_group_config_group_id_suggarchat_memory_data",
                type_="foreignkey",
            )
            safe_drop_index(batch_op, "idx_suggarchat_group_id")

        op.drop_table("suggarchat_group_config")

    if table_exists("suggarchat_memory_data"):
        with op.batch_alter_table("suggarchat_memory_data", schema=None) as batch_op:
            safe_drop_constraint(batch_op, "uq_ins_id_is_group", type_="unique")
            safe_drop_index(batch_op, "idx_ins_id")
            safe_drop_index(batch_op, "idx_is_group")

        op.drop_table("suggarchat_memory_data")

    if table_exists("suggarchat_global_insights"):
        op.drop_table("suggarchat_global_insights")
    # ### end Alembic commands ###


def downgrade(name: str = "") -> None:
    if name:
        return
    # ### commands auto generated by Alembic - please adjust! ###
    # 检查旧表是否已存在，如果不存在才创建
    if not table_exists("suggarchat_global_insights"):
        op.create_table(
            "suggarchat_global_insights",
            sa.Column("date", sa.VARCHAR(length=64), nullable=False),
            sa.Column(
                "token_input", sa.BIGINT(), server_default=sa.text("0"), nullable=False
            ),
            sa.Column(
                "token_output", sa.BIGINT(), server_default=sa.text("0"), nullable=False
            ),
            sa.Column("usage_count", sa.INTEGER(), nullable=False),
            sa.PrimaryKeyConstraint("date", name=op.f("pk_suggarchat_global_insights")),
        )

    if not table_exists("suggarchat_memory_data"):
        op.create_table(
            "suggarchat_memory_data",
            sa.Column("id", sa.INTEGER(), nullable=False),
            sa.Column("ins_id", sa.BIGINT(), nullable=False),
            sa.Column("is_group", sa.BOOLEAN(), nullable=False),
            sa.Column("time", sa.DATETIME(), nullable=False),
            sa.Column("usage_count", sa.INTEGER(), nullable=False),
            sa.Column("memory_json", sqlite.JSON(), nullable=False),
            sa.Column(
                "input_token_usage",
                sa.BIGINT(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "output_token_usage",
                sa.BIGINT(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name="pk_suggarchat_memory_data"),
            sa.UniqueConstraint("ins_id", "is_group", name="uq_ins_id_is_group"),
        )
        with op.batch_alter_table("suggarchat_memory_data", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("idx_is_group"), ["is_group"], unique=False
            )
            batch_op.create_index(batch_op.f("idx_ins_id"), ["ins_id"], unique=False)

    if not table_exists("suggarchat_group_config"):
        op.create_table(
            "suggarchat_group_config",
            sa.Column("id", sa.INTEGER(), nullable=False),
            sa.Column("group_id", sa.BIGINT(), nullable=False),
            sa.Column("enable", sa.BOOLEAN(), nullable=False),
            sa.Column("prompt", sa.TEXT(), nullable=False),
            sa.Column("fake_people", sa.BOOLEAN(), nullable=False),
            sa.Column("last_updated", sa.DATETIME(), nullable=False),
            sa.ForeignKeyConstraint(
                ["group_id"],
                ["suggarchat_memory_data.ins_id"],
                name=op.f("fk_suggarchat_group_config_group_id_suggarchat_memory_data"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_suggarchat_group_config")),
            sa.UniqueConstraint("group_id", name=op.f("uq_suggarchat_config_group_id")),
        )
        with op.batch_alter_table("suggarchat_group_config", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("idx_suggarchat_group_id"), ["group_id"], unique=False
            )

    if not table_exists("suggarchat_memory_sessions"):
        op.create_table(
            "suggarchat_memory_sessions",
            sa.Column("id", sa.INTEGER(), nullable=False),
            sa.Column("ins_id", sa.BIGINT(), nullable=False),
            sa.Column("is_group", sa.BOOLEAN(), nullable=False),
            sa.Column("created_at", sa.FLOAT(), nullable=False),
            sa.Column(
                "data", sqlite.JSON(), server_default=sa.text("'{}'"), nullable=False
            ),
            sa.ForeignKeyConstraint(
                ["ins_id"],
                ["suggarchat_memory_data.ins_id"],
                name=op.f(
                    "fk_suggarchat_memory_sessions_ins_id_suggarchat_memory_data"
                ),
            ),
            sa.ForeignKeyConstraint(
                ["is_group"],
                ["suggarchat_memory_data.is_group"],
                name=op.f(
                    "fk_suggarchat_memory_sessions_is_group_suggarchat_memory_data"
                ),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_suggarchat_memory_sessions")),
        )
        with op.batch_alter_table(
            "suggarchat_memory_sessions", schema=None
        ) as batch_op:
            batch_op.create_index(
                batch_op.f("idx_sessions_is_group"), ["is_group"], unique=False
            )
            batch_op.create_index(
                batch_op.f("idx_sessions_ins_id"), ["ins_id"], unique=False
            )
            batch_op.create_index(
                batch_op.f("idx_sessions_created_at"), ["created_at"], unique=False
            )

    # 检查新表是否存在，如果存在则删除
    if table_exists("amritabot_memory_sessions"):
        with op.batch_alter_table("amritabot_memory_sessions", schema=None) as batch_op:
            try:
                batch_op.drop_index("idx_sessions_user_id")
            except Exception as e:
                error_msg = str(e).lower()
                if (
                    "not found" in error_msg
                    or "doesn't exist" in error_msg
                    or "no index" in error_msg
                ):
                    pass  # 索引不存在，忽略
                else:
                    raise
            try:
                batch_op.drop_index("idx_sessions_created_at_time")
            except Exception as e:
                error_msg = str(e).lower()
                if (
                    "not found" in error_msg
                    or "doesn't exist" in error_msg
                    or "no index" in error_msg
                ):
                    pass  # 索引不存在，忽略
                else:
                    raise

        op.drop_table("amritabot_memory_sessions")

    if table_exists("amritabot_memory_data"):
        op.drop_table("amritabot_memory_data")

    if table_exists("amrita_group_config"):
        with op.batch_alter_table("amrita_group_config", schema=None) as batch_op:
            try:
                batch_op.drop_index("idx_amrita_group_config_user_id")
            except Exception as e:
                error_msg = str(e).lower()
                if (
                    "not found" in error_msg
                    or "doesn't exist" in error_msg
                    or "no index" in error_msg
                ):
                    pass  # 索引不存在，忽略
                else:
                    raise

        op.drop_table("amrita_group_config")

    if table_exists("amritabot_user_metadata"):
        with op.batch_alter_table("amritabot_user_metadata", schema=None) as batch_op:
            try:
                batch_op.drop_index("idx_amrita_user_id_last_active")
            except Exception as e:
                error_msg = str(e).lower()
                if (
                    "not found" in error_msg
                    or "doesn't exist" in error_msg
                    or "no index" in error_msg
                ):
                    pass  # 索引不存在，忽略
                else:
                    raise

        op.drop_table("amritabot_user_metadata")

    if table_exists("amritabot_global_insights"):
        op.drop_table("amritabot_global_insights")
    # ### end Alembic commands ###
