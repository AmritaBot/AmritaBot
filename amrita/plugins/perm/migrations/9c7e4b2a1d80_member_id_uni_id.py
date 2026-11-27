"""migrate lp member_id to platform uni_id

迁移 ID: 9c7e4b2a1d80
父迁移: 8f3a1c2d4b6e
创建时间: 2026-11-27 12:00:00.000000

1. 将 ``lp_member_permission`` 与 ``lp_member_to_permission_group`` 的 ``member_id``
   从历史裸 ID（如 ``3196373166``）迁移到跨平台 ``uni_id`` 命名空间
   （``QQPlatform_Private_{id}`` / ``QQPlatform_Group_{id}``），避免多平台挂载时
   不同平台的数字 ID 互相碰撞。
2. 顺手修复历史单列外键 ``lp_member_to_permission_group.member_id ->
   lp_member_permission.member_id`` 指向非唯一列的问题，升级为复合外键
   ``(member_id, member_type) -> lp_member_permission.(member_id, type)``，
   与 ``uq_lp_member_permission_member_id_type`` 精确对齐（在开启外键检查的 SQLite
   以及 PostgreSQL / MySQL 下均可正常工作）。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from nonebot import logger

revision: str = "9c7e4b2a1d80"
down_revision: str | Sequence[str] | None = "8f3a1c2d4b6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "8b619d7fca40"

_PERM_TABLE = "lp_member_permission"
_REL_TABLE = "lp_member_to_permission_group"
_TMP_SUFFIX = "_uni_id_tmp"

_UNI_ID_PATTERN = re.compile(r"^(?:.+?)_(Private|Group|Channel)_(.+)\Z")
_QQ_UNI_ID_PATTERN = re.compile(r"^QQPlatform_(Private|Group)_(.+)\Z")


def _to_uni_id(member_id: str, member_type: str) -> str:
    """历史裸 ID → QQPlatform_{Private|Group}_{id}；已是 uni_id 则原样返回（幂等）。"""
    if _UNI_ID_PATTERN.match(member_id):
        return member_id
    extra = "Group" if member_type == "group" else "Private"
    return f"QQPlatform_{extra}_{member_id}"


def _to_legacy_id(member_id: str, member_type: str) -> str:
    """回滚：仅还原 QQPlatform_{Private|Group}_{id}，保留其他平台 uni_id。"""
    match = _QQ_UNI_ID_PATTERN.match(member_id)
    if not match:
        return member_id
    expected = "Group" if member_type == "group" else "Private"
    if match.group(1) != expected:
        return member_id
    return match.group(2)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _quote(*names: str) -> str:
    quote = op.get_bind().dialect.identifier_preparer.quote
    return ", ".join(quote(name) for name in names)


def _tmp_name(table: str) -> str:
    return f"_{table}{_TMP_SUFFIX}"


def _create_perm_table(table_name: str, *, temporary: bool = False) -> None:
    uq_name = (
        f"uq_lp_member_permission_member_id_type{_TMP_SUFFIX}"
        if temporary
        else "uq_lp_member_permission_member_id_type"
    )
    pk_name = (
        f"pk_lp_member_permission{_TMP_SUFFIX}"
        if temporary
        else op.f("pk_lp_member_permission")
    )
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("member_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=255), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=pk_name),
        sa.UniqueConstraint("member_id", "type", name=uq_name),
        info={"bind_key": "perm"},
    )


def _create_rel_table(
    table_name: str, *, temporary: bool = False, composite_fk: bool = True
) -> None:
    constraints: list[sa.schema.SchemaItem] = []
    if not temporary:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["group_name"],
                ["lp_permission_group.group_name"],
                name=op.f(
                    "fk_lp_member_to_permission_group_group_name_lp_permission_group"
                ),
                ondelete="CASCADE",
            )
        )
        if composite_fk:
            constraints.append(
                sa.ForeignKeyConstraint(
                    ["member_id", "member_type"],
                    ["lp_member_permission.member_id", "lp_member_permission.type"],
                    name="fk_lp_member_to_permission_group_member_lp_member_permission",
                    ondelete="CASCADE",
                )
            )
        else:
            constraints.append(
                sa.ForeignKeyConstraint(
                    ["member_id"],
                    ["lp_member_permission.member_id"],
                    name=op.f(
                        "fk_lp_member_to_permission_group_member_id_lp_member_permission"
                    ),
                    ondelete="CASCADE",
                )
            )
    pk_name = (
        f"pk_lp_member_to_permission_group{_TMP_SUFFIX}"
        if temporary
        else op.f("pk_lp_member_to_permission_group")
    )
    uq_name = (
        f"uq_lp_member_to_permission_group_and_member{_TMP_SUFFIX}"
        if temporary
        else "uq_lp_member_to_permission_group_and_member"
    )
    constraints.append(sa.PrimaryKeyConstraint("id", name=pk_name))
    constraints.append(
        sa.UniqueConstraint("member_id", "group_name", "member_type", name=uq_name)
    )
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("member_id", sa.String(length=255), nullable=False),
        sa.Column("member_type", sa.String(length=255), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        *constraints,
        info={"bind_key": "perm"},
    )


def _copy(src: str, dst: str, columns: list[str]) -> None:
    names = _quote(*columns)
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_quote(dst)} ({names}) SELECT {names} FROM {_quote(src)}"
        )
    )


def _sync_sequence(table: str) -> None:
    """PostgreSQL 显式写入主键不会推进序列，重建后手动对齐。"""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    seq_name = bind.execute(
        sa.text("SELECT pg_get_serial_sequence(:table, 'id')"),
        {"table": table},
    ).scalar()
    if not seq_name:
        return
    bind.execute(
        sa.text(
            f"SELECT setval(:seq, COALESCE(MAX(id), 0) + 1, false) FROM {_quote(table)}"
        ),
        {"seq": seq_name},
    )


def _build_mapping(
    convert: Callable[[str, str], str],
    has_perm: bool,
    has_rel: bool,
) -> dict[tuple[str, str], str]:
    """按 (member_id, member_type) 构造改写映射，目标已存在或撞键时跳过。"""
    bind = op.get_bind()
    perm_existing: set[tuple[str, str]] = set()
    rel_existing: set[tuple[str, str, str]] = set()
    candidates: set[tuple[str, str]] = set()

    if has_perm:
        rows = bind.execute(
            sa.text(
                f"SELECT {_quote('member_id')}, {_quote('type')} "
                f"FROM {_quote(_PERM_TABLE)}"
            )
        ).all()
        for mid, mtype in rows:
            perm_existing.add((mid, mtype))
            candidates.add((mid, mtype))

    if has_rel:
        rows = bind.execute(
            sa.text(
                f"SELECT {_quote('member_id')}, {_quote('member_type')}, "
                f"{_quote('group_name')} FROM {_quote(_REL_TABLE)}"
            )
        ).all()
        for mid, mtype, gname in rows:
            rel_existing.add((mid, mtype, gname))
            candidates.add((mid, mtype))

    mapping: dict[tuple[str, str], str] = {}
    claimed_perm = set(perm_existing)
    claimed_rel = set(rel_existing)
    for mid, mtype in sorted(candidates):
        new_id = convert(mid, mtype)
        if new_id == mid:
            continue
        if (new_id, mtype) in claimed_perm:
            logger.warning(
                f"{_PERM_TABLE} 中已存在 ({new_id}, {mtype})，跳过 ({mid}, {mtype}) 的迁移"
            )
            continue
        member_groups = [
            gname
            for old_mid, old_mtype, gname in rel_existing
            if old_mid == mid and old_mtype == mtype
        ]
        if any((new_id, mtype, gname) in claimed_rel for gname in member_groups):
            logger.warning(
                f"{_REL_TABLE} 中已存在目标关联 ({new_id}, {mtype})，跳过 ({mid}, {mtype}) 的迁移"
            )
            continue
        mapping[(mid, mtype)] = new_id
        claimed_perm.add((new_id, mtype))
        for gname in member_groups:
            claimed_rel.add((new_id, mtype, gname))
    return mapping


def _needs_fk_change(has_rel: bool, *, composite_fk: bool) -> bool:
    """检查子表指向父表的外键形态是否与目标一致（升级/降级对称判断）。"""
    if not has_rel:
        return False
    expected_cols = ["member_id", "member_type"] if composite_fk else ["member_id"]
    fks = _inspector().get_foreign_keys(_REL_TABLE)
    for fk in fks:
        if (
            fk.get("referred_table") == _PERM_TABLE
            and fk.get("constrained_columns") == expected_cols
        ):
            return False
    return True


def _backfill_orphan_parents(perm_tmp: str, rel_tmp: str) -> None:
    """通过 SQLAlchemy JSON 列类型补齐关联表中的历史孤儿父记录，兼容全部数据库方言。"""
    bind = op.get_bind()
    q_mid = _quote("member_id")
    q_type = _quote("type")
    q_mtype = _quote("member_type")
    orphans = bind.execute(
        sa.text(
            f"SELECT DISTINCT r.{q_mid}, r.{q_mtype} "
            f"FROM {_quote(rel_tmp)} r "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM {_quote(perm_tmp)} p "
            f"  WHERE p.{q_mid} = r.{q_mid} AND p.{q_type} = r.{q_mtype}"
            f")"
        )
    ).all()
    if not orphans:
        return

    logger.warning(
        f"{_REL_TABLE} 中检测到 {len(orphans)} 条历史孤儿关联，已自动补齐空父记录"
    )
    perm_tmp_table = sa.table(
        perm_tmp,
        sa.column("member_id", sa.String(length=255)),
        sa.column("type", sa.String(length=255)),
        sa.column("permissions", sa.JSON()),
    )
    bind.execute(
        perm_tmp_table.insert(),
        [
            {"member_id": mid, "type": mtype, "permissions": {}}
            for mid, mtype in orphans
        ],
    )


def _rewrite(convert: Callable[[str, str], str], *, composite_fk: bool) -> None:
    insp = _inspector()
    has_perm = insp.has_table(_PERM_TABLE)
    has_rel = insp.has_table(_REL_TABLE)
    if not has_perm and not has_rel:
        return

    mapping = _build_mapping(convert, has_perm, has_rel)
    needs_rebuild = bool(mapping) or _needs_fk_change(
        has_rel, composite_fk=composite_fk
    )
    if not needs_rebuild:
        return

    perm_cols = ["id", "member_id", "type", "permissions"]
    rel_cols = ["id", "member_id", "member_type", "group_name"]
    perm_tmp = _tmp_name(_PERM_TABLE)
    rel_tmp = _tmp_name(_REL_TABLE)

    # 1. 建临时表并整表拷出（不带外键约束）
    if has_perm:
        if insp.has_table(perm_tmp):
            op.drop_table(perm_tmp)
        _create_perm_table(perm_tmp, temporary=True)
        _copy(_PERM_TABLE, perm_tmp, perm_cols)

    if has_rel:
        if insp.has_table(rel_tmp):
            op.drop_table(rel_tmp)
        _create_rel_table(rel_tmp, temporary=True)
        _copy(_REL_TABLE, rel_tmp, rel_cols)

    # 2. 在临时表内按 (member_id, type) 改写
    bind = op.get_bind()
    q_mid = _quote("member_id")
    q_type = _quote("type")
    q_mtype = _quote("member_type")
    for (old_id, mtype), new_id in mapping.items():
        if has_perm:
            bind.execute(
                sa.text(
                    f"UPDATE {_quote(perm_tmp)} SET {q_mid} = :new "
                    f"WHERE {q_mid} = :old AND {q_type} = :mtype"
                ),
                {"new": new_id, "old": old_id, "mtype": mtype},
            )
        if has_rel:
            bind.execute(
                sa.text(
                    f"UPDATE {_quote(rel_tmp)} SET {q_mid} = :new "
                    f"WHERE {q_mid} = :old AND {q_mtype} = :mtype"
                ),
                {"new": new_id, "old": old_id, "mtype": mtype},
            )

    # 若关联表中存在历史孤儿行（父表无对应 (member_id, type)），补齐空父记录避免复合外键拷回失败
    if has_perm and has_rel and composite_fk:
        _backfill_orphan_parents(perm_tmp, rel_tmp)

    # 3. 删除旧表（先删子表再删父表）
    if has_rel:
        op.drop_table(_REL_TABLE)
    if has_perm:
        op.drop_table(_PERM_TABLE)

    # 4. 按新定义重建表与索引
    if has_perm:
        _create_perm_table(_PERM_TABLE)
        op.create_index(
            "idx_lp_member_permission_member_id_type",
            _PERM_TABLE,
            ["member_id", "type"],
            unique=False,
        )

    if has_rel:
        _create_rel_table(_REL_TABLE, composite_fk=composite_fk)
        op.create_index(
            "idx_lp_member_to_permission_group_group_name",
            _REL_TABLE,
            ["group_name"],
            unique=False,
        )
        op.create_index(
            "idx_lp_member_to_permission_group_member_id",
            _REL_TABLE,
            ["member_id"],
            unique=False,
        )
        op.create_index(
            "idx_lp_member_to_permission_group_member_type",
            _REL_TABLE,
            ["member_type"],
            unique=False,
        )

    # 5. 数据拷回（先父表再子表）
    if has_perm:
        _copy(perm_tmp, _PERM_TABLE, perm_cols)
    if has_rel:
        _copy(rel_tmp, _REL_TABLE, rel_cols)

    # 6. 清理临时表并同步 PostgreSQL 序列
    if has_rel:
        op.drop_table(rel_tmp)
        _sync_sequence(_REL_TABLE)
    if has_perm:
        op.drop_table(perm_tmp)
        _sync_sequence(_PERM_TABLE)


def upgrade(name: str = "") -> None:
    if name:
        return
    _rewrite(_to_uni_id, composite_fk=True)


def downgrade(name: str = "") -> None:
    if name:
        return
    _rewrite(_to_legacy_id, composite_fk=False)
