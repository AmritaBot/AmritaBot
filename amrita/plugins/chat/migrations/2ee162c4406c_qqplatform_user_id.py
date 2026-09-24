"""qqplatform_user_id

迁移 ID: 2ee162c4406c
父迁移: a727d1697fba

占位迁移，不执行任何数据操作。

该 revision 被 1.8.0 发布的 c254b6952d47 引用为父迁移，但当初只存在于未合并的
重构分支上，导致 alembic 构建 revision 图时找不到它并抛出 KeyError，任何数据库
启动都会失败。这里补回该 revision 以恢复迁移图。

真正的会话 ID 改写（user_{id} / group_{id} → QQPlatform_Private_{id} /
QQPlatform_Group_{id}）全部由后继的 4b1e6d9c7a05 完成：2ee162c4406c 是
c254b6952d47 的祖先，已经停在 c254b6952d47 的数据库不会再执行它；而
4b1e6d9c7a05 是新的 head，任何数据库升级时都必然执行且只执行一次。
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "2ee162c4406c"
down_revision: str | Sequence[str] | None = "a727d1697fba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade(name: str = "") -> None:
    if name:
        return


def downgrade(name: str = "") -> None:
    if name:
        return
