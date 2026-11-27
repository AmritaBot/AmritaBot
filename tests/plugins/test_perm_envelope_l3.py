"""验证 L3 权限层 Envelope 化、跨平台 uni_id 命名空间迁移与平台边界补强。"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import nonebot
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11.event import (
    FriendRequestEvent,
    GroupBanNoticeEvent,
    GroupMessageEvent,
    HeartbeatMetaEvent,
)
from nonebot.adapters.onebot.v11.message import Message, MessageSegment
from nonebot.permission import Permission

from amrita.platform.dto import GROUP, MESSAGE, META, PRIVATE, Actor, Envelope, Scope
from amrita.platform.impl.qq.milky import MilkyPort
from amrita.platform.impl.qq.onebot import OneBotPort
from amrita.platform.ports import CapabilityMissing


@pytest.fixture(scope="module", autouse=True)
def _init_perm():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    if nonebot.get_plugin("perm") is None:
        nonebot.load_plugin("amrita.plugins.perm")


class _UnknownEvent(Event):
    def get_type(self) -> str:
        return "meta_event"

    def get_event_name(self) -> str:
        return "unknown"

    def get_event_description(self) -> str:
        return "unknown"

    def get_message(self):
        raise ValueError("no message")

    def get_user_id(self) -> str:
        raise ValueError("no user")

    def get_session_id(self) -> str:
        raise ValueError("no session")

    def is_tome(self) -> bool:
        return False


class _DummyBot(Bot):
    def __init__(self) -> None:
        pass

    async def send(self, event, message, **kwargs):
        return None


def test_perm_rules_via_nonebot_permission_di_for_meta_and_unknown_events():
    """NoneBot Permission DI 注入 OptionalEnvelopeNBDep 时，meta 与未知事件均静默返回 False。"""
    from amrita.plugins.perm.API.admin import is_lp_admin
    from amrita.plugins.perm.API.rules import (
        GroupPermissionChecker,
        UserPermissionChecker,
        any_has_permission,
    )

    hb = HeartbeatMetaEvent(
        time=1700000000,
        self_id=10000,
        post_type="meta_event",
        meta_event_type="heartbeat",
        status={"online": True, "good": True},
        interval=5000,
    )
    unknown = _UnknownEvent()
    bot = _DummyBot()

    perms = [
        Permission(is_lp_admin),
        Permission(any_has_permission("amrita.status")),
        Permission(UserPermissionChecker("amrita.status").checker()),
        Permission(GroupPermissionChecker("amrita.status", only_group=True).checker()),
        Permission(GroupPermissionChecker("amrita.status", only_group=False).checker()),
    ]
    for ev in (hb, unknown):
        for perm in perms:
            assert asyncio.run(perm(bot, ev)) is False


def test_perm_rules_work_with_cross_platform_envelope_and_isolation():
    """跨平台 Envelope 走 uni_id 主键，QQ 与 Telegram 同号严格隔离。"""
    from amrita.plugins.perm.API.admin import is_lp_admin_for
    from amrita.plugins.perm.API.rules import (
        GroupPermissionChecker,
        UserPermissionChecker,
        _check_group_permission_with_cache,
        _check_user_permission_with_cache,
        _event_to_keys,
        has_any_permission,
    )

    _check_group_permission_with_cache.cache_clear()
    _check_user_permission_with_cache.cache_clear()
    _event_to_keys.clear()

    tg_group_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=GROUP, id="-100888"),
        actor=Actor(platform="telegram", user_id="555001"),
        dedupe_key="tg:msg:-100888:42",
    )
    tg_private_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=PRIVATE, id="555001"),
        actor=Actor(platform="telegram", user_id="555001"),
        dedupe_key="tg:msg:555001:43",
    )
    # 故意构造与 TG 相同数字 ID 的 QQ 事件，确认不会互相越权
    qq_same_id_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="qq", kind=PRIVATE, id="555001"),
        actor=Actor(platform="qq", user_id="555001"),
        dedupe_key="qq:msg:44",
    )
    meta_env = Envelope(
        kind=META,
        scope=Scope(platform="qq", kind=PRIVATE, id="10000"),
        actor=Actor(platform="qq", user_id="10000"),
    )

    fake_store = AsyncMock()
    fake_store.get_member_related_permission_groups.return_value = SimpleNamespace(
        groups=[]
    )
    fake_store.permission_group_exists.return_value = False
    fake_store.get_member_permission.side_effect = lambda member_id, type="user": (
        SimpleNamespace(
            permissions={"amrita.status": True}
            if (type == "group" and member_id == "TelegramPlatform_Group_-100888")
            else {"lp.admin": True}
            if (type == "user" and member_id == "TelegramPlatform_Private_555001")
            else {}
        )
    )

    fake_dm = SimpleNamespace(config=SimpleNamespace(enable=True))

    async def _run_checks() -> None:
        assert await has_any_permission(tg_group_env, "amrita.status") is True
        assert (
            await GroupPermissionChecker("amrita.status", True)._check_permission(
                tg_private_env, "amrita.status"
            )
            is False
        )
        assert (
            await GroupPermissionChecker("amrita.status", False)._check_permission(
                tg_private_env, "amrita.status"
            )
            is True
        )
        assert (
            await UserPermissionChecker("lp.admin")._check_permission(
                tg_private_env, "lp.admin"
            )
            is True
        )
        assert await is_lp_admin_for(tg_private_env) is True
        # QQ 同号 555001 不应继承 TG 555001 的 lp.admin
        assert await is_lp_admin_for(qq_same_id_env) is False
        assert await is_lp_admin_for(meta_env) is False

    with (
        patch(
            "amrita.plugins.perm.API.rules.PermissionStorage", return_value=fake_store
        ),
        patch("amrita.plugins.perm.API.admin.DataManager", return_value=fake_dm),
        patch("amrita.plugins.perm.API.admin.ENV_ADMINS", set()),
    ):
        asyncio.run(_run_checks())

    assert "tg:msg:-100888:42" in _event_to_keys
    assert "tg:msg:555001:43" in _event_to_keys


def test_perm_identity_resolution_and_superuser_matching():
    """resolve_member_id 与 matches_superuser 支持裸 ID、platform:id 与完整 uni_id。"""
    from amrita.plugins.perm.identity import matches_superuser, resolve_member_id

    assert resolve_member_id("3196373166", "user") == "QQPlatform_Private_3196373166"
    assert (
        resolve_member_id("12345", "user", default_platform="telegram")
        == "TelegramPlatform_Private_12345"
    )
    assert (
        resolve_member_id("telegram:-100123", "group", default_platform="qq")
        == "TelegramPlatform_Group_-100123"
    )
    assert (
        resolve_member_id("TelegramPlatform_Group_-100123", "group")
        == "TelegramPlatform_Group_-100123"
    )

    tg_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=PRIVATE, id="77001"),
        actor=Actor(platform="telegram", user_id="77001"),
    )
    qq_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="qq", kind=PRIVATE, id="77001"),
        actor=Actor(platform="qq", user_id="77001"),
    )
    assert matches_superuser(tg_env, {"77001"}) is True
    assert matches_superuser(tg_env, {"telegram:77001"}) is True
    assert matches_superuser(qq_env, {"telegram:77001"}) is False
    assert matches_superuser(tg_env, {"TelegramPlatform_Private_77001"}) is True
    assert matches_superuser(qq_env, {"TelegramPlatform_Private_77001"}) is False


def test_perm_alembic_migration_member_id_to_uni_id_and_downgrade(tmp_path: Path):
    """验证 9c7e4b2a1d80 迁移在带外键约束的 SQLite 下升级、幂等与降级均保持数据一致。"""
    mig_dir = Path("amrita/plugins/perm/migrations")

    def _load_mod(path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    init_mig = _load_mod(mig_dir / "8b619d7fca40_refactor.py")
    uni_mig = _load_mod(mig_dir / "9c7e4b2a1d80_member_id_uni_id.py")

    db_file = tmp_path / "perm_mig.sqlite3"
    engine = sa.create_engine(f"sqlite:///{db_file}")

    # 历史表 8b619d7fca40 的单列 FK 指向非唯一列，SQLite 默认外键关闭状态下建表并写入历史数据，
    # 迁移升级为复合外键后开启 PRAGMA foreign_keys=ON 验证外键完整且可正常读写。
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            init_mig.upgrade()

        conn.execute(
            sa.text(
                "INSERT INTO lp_permission_group (group_name, permissions) "
                "VALUES ('vip', '{\"amrita.status\": true}')"
            )
        )
        # 历史裸 ID（同号 12345 同时作为 user 和 group，验证按 type 分别迁移）
        conn.execute(
            sa.text(
                "INSERT INTO lp_member_permission (member_id, type, permissions) VALUES "
                "('12345', 'user', '{\"lp.admin\": true}'), "
                "('12345', 'group', '{\"amrita.status\": true}'), "
                "('TelegramPlatform_Private_77001', 'user', '{\"lp.admin\": true}')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO lp_member_to_permission_group (member_id, member_type, group_name) VALUES "
                "('12345', 'user', 'vip'), "
                "('12345', 'group', 'vip'), "
                "('TelegramPlatform_Private_77001', 'user', 'vip')"
            )
        )

    # 1. 执行 upgrade
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            uni_mig.upgrade()

    # 新连接用 AUTOCOMMIT 在事务外启用 PRAGMA foreign_keys=ON，验证复合外键与 ON DELETE CASCADE
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as fk_conn:
        fk_conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        if True:
            assert fk_conn.execute(sa.text("PRAGMA foreign_key_check")).all() == []
            fk_conn.execute(
                sa.text(
                    "INSERT INTO lp_member_permission (member_id, type, permissions) "
                    "VALUES ('QQPlatform_Private_999', 'user', '{}')"
                )
            )
            fk_conn.execute(
                sa.text(
                    "INSERT INTO lp_member_to_permission_group (member_id, member_type, group_name) "
                    "VALUES ('QQPlatform_Private_999', 'user', 'vip')"
                )
            )
            fk_conn.execute(
                sa.text(
                    "DELETE FROM lp_member_permission WHERE member_id = 'QQPlatform_Private_999'"
                )
            )
        fk_conn.execute(sa.text("PRAGMA foreign_keys=OFF"))

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)

        perms = sorted(
            conn.execute(
                sa.text("SELECT member_id, type, permissions FROM lp_member_permission")
            ).all()
        )
        rels = sorted(
            conn.execute(
                sa.text(
                    "SELECT member_id, member_type, group_name FROM lp_member_to_permission_group"
                )
            ).all()
        )
        assert perms == [
            ("QQPlatform_Group_12345", "group", '{"amrita.status": true}'),
            ("QQPlatform_Private_12345", "user", '{"lp.admin": true}'),
            ("TelegramPlatform_Private_77001", "user", '{"lp.admin": true}'),
        ]
        assert rels == [
            ("QQPlatform_Group_12345", "group", "vip"),
            ("QQPlatform_Private_12345", "user", "vip"),
            ("TelegramPlatform_Private_77001", "user", "vip"),
        ]

        # 2. 再次执行 upgrade 应完全幂等
        with Operations.context(ctx):
            uni_mig.upgrade()
        assert (
            sorted(
                conn.execute(
                    sa.text(
                        "SELECT member_id, type, permissions FROM lp_member_permission"
                    )
                ).all()
            )
            == perms
        )

        # 3. 执行 downgrade：关闭外键检查还原历史单列 FK，QQ 还原裸 ID，Telegram uni_id 保留
        with Operations.context(ctx):
            uni_mig.downgrade()
        perms_down = sorted(
            conn.execute(
                sa.text("SELECT member_id, type FROM lp_member_permission")
            ).all()
        )
        rels_down = sorted(
            conn.execute(
                sa.text(
                    "SELECT member_id, member_type, group_name FROM lp_member_to_permission_group"
                )
            ).all()
        )
        assert perms_down == [
            ("12345", "group"),
            ("12345", "user"),
            ("TelegramPlatform_Private_77001", "user"),
        ]
        assert rels_down == [
            ("12345", "group", "vip"),
            ("12345", "user", "vip"),
            ("TelegramPlatform_Private_77001", "user", "vip"),
        ]

    engine.dispose()


def test_perm_alembic_migration_empty_table_fk_symmetry_and_orphan_backfill(
    tmp_path: Path,
):
    """空表升降级外键对称切换，且历史孤儿关联行在升级时自动补齐 JSON 空父记录。"""
    mig_dir = Path("amrita/plugins/perm/migrations")

    def _load_mod(path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    init_mig = _load_mod(mig_dir / "8b619d7fca40_refactor.py")
    uni_mig = _load_mod(mig_dir / "9c7e4b2a1d80_member_id_uni_id.py")

    def _rel_fk_cols(conn: sa.Connection) -> list[str]:
        fks = sa.inspect(conn).get_foreign_keys("lp_member_to_permission_group")
        for fk in fks:
            if fk.get("referred_table") == "lp_member_permission":
                return list(fk["constrained_columns"])
        return []

    # 1. 空表：upgrade 升级为复合外键，downgrade 对称回退到单列外键
    empty_engine = sa.create_engine(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    with empty_engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            init_mig.upgrade()
        assert _rel_fk_cols(conn) == ["member_id"]

        with Operations.context(ctx):
            uni_mig.upgrade()
        assert _rel_fk_cols(conn) == ["member_id", "member_type"]

        with Operations.context(ctx):
            uni_mig.downgrade()
        assert _rel_fk_cols(conn) == ["member_id"]
    empty_engine.dispose()

    # 2. 孤儿关联行 + 冲突跳过：子表有行但父表缺失 -> 自动补空 {}；目标已存在 -> 跳过不报错
    orphan_engine = sa.create_engine(f"sqlite:///{tmp_path / 'orphan.sqlite3'}")
    with orphan_engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            init_mig.upgrade()
        conn.execute(
            sa.text(
                "INSERT INTO lp_permission_group (group_name, permissions) "
                "VALUES ('vip', '{}')"
            )
        )
        # 孤儿关联行（父表无 88888）+ 已冲突行（同时存在 10001 和 QQPlatform_Private_10001）
        conn.execute(
            sa.text(
                "INSERT INTO lp_member_permission (member_id, type, permissions) VALUES "
                "('10001', 'user', '{\"old\": true}'), "
                "('QQPlatform_Private_10001', 'user', '{\"new\": true}')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO lp_member_to_permission_group (member_id, member_type, group_name) "
                "VALUES ('88888', 'group', 'vip')"
            )
        )
        with Operations.context(ctx):
            uni_mig.upgrade()

        perms = sorted(
            conn.execute(
                sa.text("SELECT member_id, type, permissions FROM lp_member_permission")
            ).all()
        )
        rels = sorted(
            conn.execute(
                sa.text(
                    "SELECT member_id, member_type, group_name FROM lp_member_to_permission_group"
                )
            ).all()
        )
        assert ("QQPlatform_Group_88888", "group", "{}") in perms
        assert ("10001", "user", '{"old": true}') in perms
        assert ("QQPlatform_Private_10001", "user", '{"new": true}') in perms
        assert rels == [("QQPlatform_Group_88888", "group", "vip")]

    with orphan_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as fk_conn:
        fk_conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        assert fk_conn.execute(sa.text("PRAGMA foreign_key_check")).all() == []
    orphan_engine.dispose()


def test_perm_plugin_meta_has_no_onebot_adapter_restriction():
    from amrita.plugins import perm

    assert perm.__plugin_meta__.supported_adapters is None


def test_platform_boundary_thread_rejected_and_dedupe_discriminates():
    """QQ Sender 拒绝 thread 参数；同类同秒非消息事件 dedupe_key 不撞键。"""
    scope = Scope(platform="qq", kind=GROUP, id="789")
    onebot_sender = OneBotPort().sender(cast(Bot, _DummyBot()), scope)
    milky_sender = MilkyPort().sender(cast(Bot, _DummyBot()), scope)

    with pytest.raises(CapabilityMissing):
        asyncio.run(onebot_sender.send_text("hi", thread="topic-1"))
    with pytest.raises(CapabilityMissing):
        asyncio.run(onebot_sender.send_parts((), thread="topic-1"))
    with pytest.raises(CapabilityMissing):
        asyncio.run(milky_sender.send_text("hi", thread="topic-1"))
    with pytest.raises(CapabilityMissing):
        asyncio.run(milky_sender.send_parts((), thread="topic-1"))

    # 同秒同人两次不同 flag 的加好友请求，dedupe_key 必须不同
    r1 = FriendRequestEvent(
        time=1700000000,
        self_id=10000,
        post_type="request",
        request_type="friend",
        user_id=123,
        comment="hi",
        flag="flag-A",
    )
    r2 = FriendRequestEvent(
        time=1700000000,
        self_id=10000,
        post_type="request",
        request_type="friend",
        user_id=123,
        comment="hi",
        flag="flag-B",
    )
    e1 = OneBotPort().to_envelope(r1)
    e2 = OneBotPort().to_envelope(r2)
    assert e1.dedupe_key != e2.dedupe_key

    # 同秒不同 sub_type（禁言 vs 解禁）的群禁言事件，dedupe_key 必须不同
    b1 = GroupBanNoticeEvent(
        time=1700000000,
        self_id=10000,
        post_type="notice",
        notice_type="group_ban",
        sub_type="ban",
        group_id=789,
        operator_id=111,
        user_id=123,
        duration=60,
    )
    b2 = GroupBanNoticeEvent(
        time=1700000000,
        self_id=10000,
        post_type="notice",
        notice_type="group_ban",
        sub_type="lift_ban",
        group_id=789,
        operator_id=111,
        user_id=123,
        duration=0,
    )
    assert (
        OneBotPort().to_envelope(b1).dedupe_key
        != OneBotPort().to_envelope(b2).dedupe_key
    )

    # 消息事件仍保持原有 qq:msg:<id> 键形
    gm = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=456,
        message=Message([MessageSegment.text("hi")]),
        raw_message="hi",
        font=0,
        sender={"user_id": 123, "nickname": "N"},
        to_me=False,
        group_id=789,
    )
    assert OneBotPort().to_envelope(gm).dedupe_key == "qq:msg:456"
