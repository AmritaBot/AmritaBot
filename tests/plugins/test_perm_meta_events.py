"""权限检查不能再因为 meta 事件没有发起者而抛异常。

1.20.x 的实测故障：``AlconnaMatcherMeta`` 的 type 为空，心跳事件也会进权限检查，
而 ``is_lp_admin`` / ``UserPermissionChecker`` 直接调 ``event.get_user_id()``，
抛 ``ValueError: Event has no context!``，整条事件被判失败。
"""

from __future__ import annotations

import asyncio

import nonebot
import pytest
from nonebot.adapters.onebot.v11.event import (
    GroupMessageEvent,
    HeartbeatMetaEvent,
    LifecycleMetaEvent,
)
from nonebot.adapters.onebot.v11.message import Message, MessageSegment


@pytest.fixture(scope="module", autouse=True)
def _init_driver():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


def _heartbeat() -> HeartbeatMetaEvent:
    return HeartbeatMetaEvent(
        time=1700000000,
        self_id=10000,
        post_type="meta_event",
        meta_event_type="heartbeat",
        status={"online": True, "good": True},
        interval=5000,
    )


def _lifecycle() -> LifecycleMetaEvent:
    return LifecycleMetaEvent(
        time=1700000000,
        self_id=10000,
        post_type="meta_event",
        meta_event_type="lifecycle",
        sub_type="connect",
    )


def _group_message() -> GroupMessageEvent:
    return GroupMessageEvent(
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
        sender={"user_id": 123, "nickname": "N", "role": "member"},
        to_me=False,
        group_id=789,
    )


def test_is_lp_admin_is_false_for_meta_events():
    from amrita.plugins.perm.API.admin import is_lp_admin

    for event in (_heartbeat(), _lifecycle()):
        assert asyncio.run(is_lp_admin(event)) is False


def test_any_has_permission_is_false_for_meta_events():
    from amrita.plugins.perm.API.rules import any_has_permission

    checker = any_has_permission("lp.admin")
    for event in (_heartbeat(), _lifecycle()):
        assert asyncio.run(checker(event)) is False


def test_user_permission_checker_is_false_for_meta_events():
    from amrita.plugins.perm.API.rules import UserPermissionChecker

    checker = UserPermissionChecker("some.permission")
    for event in (_heartbeat(), _lifecycle()):
        assert asyncio.run(checker._check_permission(event, "some.permission")) is False


def test_user_id_helper_reads_message_events():
    from amrita.utils.events import event_user_id

    assert event_user_id(_group_message()) == "123"
    assert event_user_id(_heartbeat()) is None
