"""widen context record user id

迁移 ID: 8f3a1c2d4b6e
父迁移: 3d5c1a7e9b42
创建时间: 2026-11-21 08:05:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f3a1c2d4b6e"
down_revision: str | Sequence[str] | None = "3d5c1a7e9b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("amrita_chat_context_record", schema=None) as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(32),
            type_=sa.String(64),
            existing_nullable=False,
        )


def downgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("amrita_chat_context_record", schema=None) as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(64),
            type_=sa.String(32),
            existing_nullable=False,
        )
