"""验证阶段 0/1/2 迁移：Alconna 命令前缀/参数/菜单状态，以及会话锁与 uni_id 收口。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import nonebot
import pytest
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11.message import Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot_plugin_alconna import Match

from amrita.platform.dto import GROUP, MESSAGE, PRIVATE, Actor, Envelope, Scope


@pytest.fixture(scope="module", autouse=True)
def _init_plugins():
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(command_start={"/", ""}, command_sep={"."})
        driver = nonebot.get_driver()
    else:
        driver.config.command_start = {"/", ""}
        driver.config.command_sep = {"."}
    # 与真实启动顺序一致：perm 先加载并 require(menu)，再加载 manager
    nonebot.load_plugin("amrita.plugins.perm")
    nonebot.load_plugin("amrita.plugins.manager")
    nonebot.load_plugin("amrita.plugins.chat")


def _parse(matcher: Any, text: str):
    return matcher._rule.command().parse(text)


def test_stage0_alconna_prefix_matching():
    from amrita.plugins.manager.amrita import amrita_cmd
    from amrita.plugins.manager.leave import set_leave
    from amrita.plugins.manager.status import status_cmd

    assert _parse(status_cmd, "/status").matched
    assert _parse(status_cmd, "status").matched
    assert _parse(amrita_cmd, "/amrita").matched
    assert _parse(amrita_cmd, "/版本").matched
    assert _parse(amrita_cmd, "关于").matched

    res_this = _parse(set_leave, "/set_leave --this")
    assert res_this.matched
    assert res_this.main_args["target"] == "--this"

    res_gid = _parse(set_leave, "/set_leave 123456")
    assert res_gid.matched
    assert res_gid.main_args["target"] == "123456"


def test_stage1_ban_pardon_parsing_and_menu_state():
    from amrita.plugins.manager.ban import ban_group, ban_user
    from amrita.plugins.manager.pardon import pardon_group, pardon_user
    from amrita.plugins.menu.models import MatcherData

    for matcher in (ban_group, ban_user, pardon_group, pardon_user):
        data = MatcherData.model_validate(matcher._default_state)
        assert data.name

    r1 = _parse(ban_group, "/ban.group 10001 刷屏 广告")
    assert r1.matched
    assert r1.main_args["target"] == "10001"
    assert r1.main_args["reason"] == ("刷屏", "广告")

    r2 = _parse(ban_user, "/ban.user 20002")
    assert r2.matched
    assert r2.main_args["target"] == "20002"
    assert "reason" not in r2.main_args

    r3 = _parse(pardon_group, "/pardon.group 10001")
    assert r3.matched
    assert r3.main_args["target"] == ("10001",)

    r4 = _parse(pardon_user, "/pardon.user")
    assert r4.matched
    assert "target" not in r4.main_args


def test_stage1_ban_handler_execution():
    from amrita.plugins.manager.ban import ban_user, ban_user_handle

    fake_bl = AsyncMock()
    fake_bl.is_private_black.return_value = False
    finished: list[str] = []

    async def _fake_finish(msg: str):
        finished.append(msg)
        raise FinishedException

    with (
        patch("amrita.plugins.manager.ban.bl_manager", fake_bl),
        patch.object(ban_user, "finish", side_effect=_fake_finish),
        pytest.raises(FinishedException),
    ):
        asyncio.run(
            ban_user_handle(
                target=Match(result="98765", available=True),
                reason=Match(result=("违规", "刷屏"), available=True),
            )
        )
    fake_bl.private_append.assert_awaited_once_with("98765", "违规 刷屏")
    assert finished == ["✅ 封禁用户98765成功！"]


def test_stage1_lp_commands_parsing_and_menu_state():
    from amrita.plugins.menu.models import MatcherData
    from amrita.plugins.perm.command_manager import command

    # main(1) + user(4) + chat_group(4) + perm_group(5) = 14 条命令
    expected_heads = {
        "lp",
        "lp.user",
        "lp.user.permission",
        "lp.user.parent",
        "lp.user.perm_group",
        "lp.chat_group",
        "lp.chat_group.permission",
        "lp.chat_group.parent",
        "lp.chat_group.perm_group",
        "lp.perm_group",
        "lp.perm_group.permission",
        "lp.perm_group.parent",
        "lp.perm_group.to",
        "lp.perm_group.list",
    }
    by_head = {m._rule.command().command: m for m in command.matchers}
    assert set(by_head) == expected_heads

    for head in ("lp", "lp.user", "lp.chat_group", "lp.perm_group"):
        data = MatcherData.model_validate(by_head[head]._default_state)
        assert data.name

    assert _parse(by_head["lp"], "/lp").matched
    assert not _parse(by_head["lp"], "/lp.user").matched

    r_perm = _parse(
        by_head["lp.user.permission"], "/lp.user.permission 123 set a.b true"
    )
    assert r_perm.matched
    assert r_perm.main_args["params"] == ("123", "set", "a.b", "true")

    assert _parse(by_head["lp.perm_group.list"], "/lp.perm_group.list").matched


def test_stage2_lock_session_guard_and_sql_unification():
    from amrita.plugins.chat.utils.lock import (
        get_group_lock,
        get_private_lock,
        get_session_lock,
    )
    from amrita.plugins.chat.utils.session_guard import session_lock
    from amrita.plugins.chat.utils.sql import get_uni_id, get_uni_user_id, make_uni_id

    group_scope = Scope(platform="qq", kind=GROUP, id="789")
    private_scope = Scope(platform="qq", kind=PRIVATE, id="123")
    tg_scope = Scope(platform="telegram", kind=GROUP, id="789")

    group_env = Envelope(
        kind=MESSAGE,
        scope=group_scope,
        actor=Actor(platform="qq", user_id="123"),
    )
    private_env = Envelope(
        kind=MESSAGE,
        scope=private_scope,
        actor=Actor(platform="qq", user_id="123"),
    )
    tg_env = Envelope(
        kind=MESSAGE,
        scope=tg_scope,
        actor=Actor(platform="telegram", user_id="123"),
    )

    assert get_uni_id(group_env) == "QQPlatform_Group_789"
    assert get_uni_id(private_scope) == "QQPlatform_Private_123"
    assert get_uni_id(tg_env) == "TelegramPlatform_Group_789"
    assert get_uni_user_id(group_env) == make_uni_id(789, is_group=True)
    assert get_uni_user_id(private_env) == make_uni_id("123", is_group=False)
    assert (
        make_uni_id("789", is_group=True, platform="telegram")
        == "TelegramPlatform_Group_789"
    )

    assert session_lock(group_env) is get_session_lock("QQPlatform_Group_789")
    assert session_lock(group_scope) is get_group_lock(789)
    assert session_lock(private_env) is get_private_lock(123)
    assert session_lock(tg_env) is not session_lock(group_env)

    v11_group = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=1,
        message=Message([MessageSegment.text("hi")]),
        raw_message="hi",
        font=0,
        sender={"user_id": 123, "nickname": "N", "role": "member"},
        to_me=False,
        group_id=789,
    )
    v11_private = PrivateMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="friend",
        user_id=123,
        message_type="private",
        message_id=2,
        message=Message([MessageSegment.text("hi")]),
        raw_message="hi",
        font=0,
        sender={"user_id": 123, "nickname": "N"},
        to_me=True,
    )
    assert get_uni_user_id(v11_group) == "QQPlatform_Group_789"
    assert get_uni_user_id(v11_private) == "QQPlatform_Private_123"
