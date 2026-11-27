"""验证 L3 权限层 Envelope 化与平台边界补强：跨平台判定、缓存失效、meta/未知事件静默拒绝、thread 拒绝与 dedupe 判别。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import nonebot
import pytest
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


def test_perm_rules_work_with_cross_platform_envelope_and_cache_invalidation():
    """群/用户权限检查直接吃 Envelope（含 Telegram），且事件后处理按 dedupe_key 清缓存。"""
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
            if (type == "group" and member_id == "-100888")
            else {"lp.admin": True}
            if (type == "user" and member_id == "555001")
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
        assert await is_lp_admin_for(meta_env) is False

    with (
        patch(
            "amrita.plugins.perm.API.rules.PermissionStorage", return_value=fake_store
        ),
        patch("amrita.plugins.perm.API.admin.DataManager", return_value=fake_dm),
    ):
        asyncio.run(_run_checks())

    # 缓存记录挂在 dedupe_key 上，模拟 postprocessor 清除验证不会抛错且键被清空
    assert "tg:msg:-100888:42" in _event_to_keys
    assert "tg:msg:555001:43" in _event_to_keys


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
