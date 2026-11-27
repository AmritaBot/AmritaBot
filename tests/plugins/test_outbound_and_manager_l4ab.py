"""验证 L4A（公共出站/管理员推送）与 L4B（menu 与 manager 迁移至 Alconna + Envelope）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import nonebot
import pytest
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11.event import (
    GroupBanNoticeEvent,
    GroupMessageEvent,
    HeartbeatMetaEvent,
)
from nonebot.adapters.onebot.v11.message import Message, MessageSegment
from nonebot.exception import FinishedException, IgnoredException
from nonebot.matcher import Matcher
from nonebot_plugin_alconna import Match

from amrita.platform.dto import (
    GROUP,
    MESSAGE,
    META,
    PRIVATE,
    Actor,
    Envelope,
    Part,
    Scope,
)


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
    if nonebot.get_plugin("perm") is None:
        nonebot.load_plugin("amrita.plugins.perm")
    if nonebot.get_plugin("manager") is None:
        nonebot.load_plugin("amrita.plugins.manager")


class _FakeOneBot(Bot):
    def __init__(self, self_id: str = "10000") -> None:
        self.self_id = self_id
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send(self, event, message, **kwargs):
        self.calls.append(("send", {"message": message}))

    async def send_group_msg(self, *, group_id: int, message: object):
        self.calls.append(
            ("send_group_msg", {"group_id": group_id, "message": message})
        )
        return {"message_id": 1}

    async def send_private_msg(self, *, user_id: int, message: object):
        self.calls.append(
            ("send_private_msg", {"user_id": user_id, "message": message})
        )
        return {"message_id": 2}

    async def send_group_forward_msg(
        self, *, group_id: int, messages: list[dict[str, object]]
    ):
        self.calls.append(
            ("send_group_forward_msg", {"group_id": group_id, "messages": messages})
        )
        return {"message_id": 3}

    async def send_private_forward_msg(
        self, *, user_id: int, messages: list[dict[str, object]]
    ):
        self.calls.append(
            ("send_private_forward_msg", {"user_id": user_id, "messages": messages})
        )
        return {"message_id": 4}

    async def set_group_leave(self, *, group_id: int):
        self.calls.append(("set_group_leave", {"group_id": group_id}))


class _FakeTelegramBot(Bot):
    __module__ = "nonebot.adapters.telegram.bot"

    def __init__(self, self_id: str = "tg_bot") -> None:
        self.self_id = self_id
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send(self, event, message, **kwargs):
        self.calls.append(("send", {"message": message}))

    async def send_message(
        self, *, chat_id: int | str, text: str, message_thread_id: int | None = None
    ):
        self.calls.append(
            (
                "send_message",
                {
                    "chat_id": chat_id,
                    "text": text,
                    "thread": message_thread_id,
                },
            )
        )
        return SimpleNamespace(message_id=99)

    async def send_to(
        self,
        chat_id: int | str,
        message: object,
        message_thread_id: int | None = None,
    ):
        self.calls.append(
            (
                "send_to",
                {
                    "chat_id": chat_id,
                    "message": message,
                    "thread": message_thread_id,
                },
            )
        )
        return SimpleNamespace(message_id=100)


class _FakeMilkyBot(Bot):
    __module__ = "nonebot.adapters.milky.bot"

    def __init__(self, self_id: str = "10000") -> None:
        self.self_id = self_id
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send(self, event, message, **kwargs):
        self.calls.append(("send", {"message": message}))

    async def send_group_message(self, *, group_id: int, message: object):
        self.calls.append(
            ("send_group_message", {"group_id": group_id, "message": message})
        )
        return SimpleNamespace(message_seq=11)

    async def send_private_message(self, *, user_id: int, message: object):
        self.calls.append(
            ("send_private_message", {"user_id": user_id, "message": message})
        )
        return SimpleNamespace(message_seq=12)

    async def quit_group(self, *, group_id: int):
        self.calls.append(("quit_group", {"group_id": group_id}))


def _parse(matcher: Any, text: str):
    return matcher._rule.command().parse(text)


def test_send_forward_msg_onebot_forward_and_non_onebot_fallback():
    """OneBot v11 与 Milky 走合并转发，Telegram 降级为平台 Sender 纯文本发送。"""
    from amrita.utils.send import send_forward_msg

    ob_bot = _FakeOneBot()
    ob_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="qq", kind=GROUP, id="123456"),
        actor=Actor(platform="qq", user_id="1001"),
        self_id="10000",
        adapter="onebot11",
    )
    asyncio.run(
        send_forward_msg(
            ob_bot,
            ob_env,
            "Menu",
            "10000",
            ["段落A", Part(kind="text", value="段落B"), MessageSegment.text("段落C")],
        )
    )
    assert ob_bot.calls[0][0] == "send_group_forward_msg"
    assert ob_bot.calls[0][1]["group_id"] == 123456
    assert len(ob_bot.calls[0][1]["messages"]) == 3

    # 兼容原始 OneBot Event 传参
    raw_event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=1001,
        message_type="group",
        message_id=42,
        message=Message([MessageSegment.text("hi")]),
        raw_message="hi",
        font=0,
        sender={"user_id": 1001, "nickname": "U"},
        to_me=False,
        group_id=654321,
    )
    asyncio.run(
        send_forward_msg(
            ob_bot, raw_event, "Legacy", "10000", [MessageSegment.text("ok")]
        )
    )
    assert ob_bot.calls[1][0] == "send_group_forward_msg"
    assert ob_bot.calls[1][1]["group_id"] == 654321

    # Milky 原生支持 OutgoingSegment(type="forward") 合并转发
    milky_bot = _FakeMilkyBot()
    milky_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="qq", kind=GROUP, id="88888"),
        actor=Actor(platform="qq", user_id="1001"),
        self_id="10000",
        adapter="milky",
    )
    asyncio.run(
        send_forward_msg(milky_bot, milky_env, "Menu", "10000", ["第一段", "第二段"])
    )
    assert milky_bot.calls[0][0] == "send_group_message"
    assert milky_bot.calls[0][1]["group_id"] == 88888
    milky_msg = milky_bot.calls[0][1]["message"]
    elements = (
        milky_msg.to_elements() if hasattr(milky_msg, "to_elements") else milky_msg
    )
    assert isinstance(elements, list)
    assert elements[0]["type"] == "forward"
    nodes = elements[0]["data"]["messages"]
    assert len(nodes) == 2
    assert nodes[0]["user_id"] == 10000
    assert nodes[0]["sender_name"] == "Menu"
    assert nodes[0]["segments"][0] == {"type": "text", "data": {"text": "第一段"}}

    # Telegram 降级为 TelegramSender 文本发送
    tg_bot = _FakeTelegramBot()
    tg_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=GROUP, id="-100777"),
        actor=Actor(platform="telegram", user_id="9001"),
        self_id="tg_bot",
        adapter="telegram",
    )
    asyncio.run(send_forward_msg(tg_bot, tg_env, "Menu", "tg_bot", ["行1", "行2"]))
    assert tg_bot.calls
    assert tg_bot.calls[0][1]["chat_id"] == -100777


def test_send_to_admin_routes_via_platform_sender_and_logs_when_disabled():
    """send_to_admin 按平台 Sender 发送，admin_group=-1 时仅写日志不调 Bot。"""
    from amrita.utils import admin as admin_mod

    ob_bot = _FakeOneBot()
    cfg_enabled = SimpleNamespace(admin_group=999999)
    with patch.object(admin_mod, "get_amrita_config", return_value=cfg_enabled):
        asyncio.run(admin_mod.send_to_admin("告警内容", ob_bot))
    assert ob_bot.calls[0][0] == "send_group_msg"
    assert ob_bot.calls[0][1]["group_id"] == 999999

    milky_bot = _FakeMilkyBot()
    with patch.object(admin_mod, "get_amrita_config", return_value=cfg_enabled):
        asyncio.run(admin_mod.send_to_admin("Milky 告警", milky_bot))
    assert milky_bot.calls[0][0] == "send_group_message"
    assert milky_bot.calls[0][1]["group_id"] == 999999

    ob_bot_idle = _FakeOneBot()
    cfg_disabled = SimpleNamespace(admin_group=-1)
    with patch.object(admin_mod, "get_amrita_config", return_value=cfg_disabled):
        asyncio.run(admin_mod.send_to_admin("仅写日志", ob_bot_idle))
    assert ob_bot_idle.calls == []


def test_l4b_alconna_commands_parsing_and_menu_state():
    """menu / blacklist / send_to.* / clean_groups / set_enable 均具备有效 default_state 与 Alconna 解析。"""
    from amrita.plugins.manager.auto_clean import clean_groups
    from amrita.plugins.manager.checker import set_enable_cmd
    from amrita.plugins.manager.list_black import black_list
    from amrita.plugins.manager.send import group as send_group
    from amrita.plugins.manager.send import user as send_user
    from amrita.plugins.menu.commands import menu_cmd
    from amrita.plugins.menu.models import MatcherData

    for matcher in (
        menu_cmd,
        black_list,
        send_group,
        send_user,
        clean_groups,
        set_enable_cmd,
    ):
        data = MatcherData.model_validate(matcher._default_state)
        assert data.name

    assert _parse(menu_cmd, "/menu").matched
    assert _parse(menu_cmd, "/菜单 --sudo").find("sudo")
    assert _parse(menu_cmd, "/help").matched
    assert _parse(black_list, "/blacklist").matched
    assert _parse(black_list, "/黑名单").matched

    sg = _parse(send_group, "/send_to.group -100123 你好 世界")
    assert sg.matched
    assert sg.main_args["target"] == "-100123"
    assert sg.main_args["content"] == ("你好", "世界")

    su = _parse(send_user, "/send_to.user 42 hello")
    assert su.matched
    assert su.main_args["target"] == "42"

    assert _parse(clean_groups, "/clean_groups").matched
    assert _parse(clean_groups, "/clean_groups --confirm").find("confirm")

    se = _parse(set_enable_cmd, "/set_enable false")
    assert se.matched
    assert se.main_args["state"] == "false"


def test_manager_black_preprocessor_uses_envelope_and_cross_adapter_leave():
    """manager/black.py 跳过 META 事件，命中群黑名单按适配器退群，命中用户黑名单静默拦截。"""
    from amrita.plugins.manager import black as black_mod

    matcher = Matcher()
    milky_bot = _FakeMilkyBot()

    meta_env = Envelope(
        kind=META,
        scope=Scope(platform="qq", kind=PRIVATE, id="10000"),
        actor=Actor(platform="qq", user_id="10000"),
        self_id="10000",
        adapter="milky",
    )
    asyncio.run(black_mod.message_preprocessor(matcher, milky_bot, meta_env))
    assert milky_bot.calls == []

    grp_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="qq", kind=GROUP, id="778899"),
        actor=Actor(platform="qq", user_id="2002"),
        self_id="10000",
        adapter="milky",
    )
    with (
        patch.object(
            black_mod.bl_manager, "is_group_black", AsyncMock(return_value=True)
        ),
        patch.object(black_mod, "send_to_admin", AsyncMock()) as mock_admin,
        pytest.raises(IgnoredException),
    ):
        asyncio.run(black_mod.message_preprocessor(matcher, milky_bot, grp_env))
    mock_admin.assert_awaited_once()
    assert milky_bot.calls == [("quit_group", {"group_id": 778899})]

    user_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=PRIVATE, id="9001"),
        actor=Actor(platform="telegram", user_id="9001"),
        self_id="tg_bot",
        adapter="telegram",
    )
    with (
        patch.object(
            black_mod.bl_manager,
            "is_private_black",
            AsyncMock(side_effect=lambda uid: uid == "TelegramPlatform_Private_9001"),
        ),
        pytest.raises(IgnoredException),
    ):
        asyncio.run(
            black_mod.message_preprocessor(matcher, _FakeTelegramBot(), user_env)
        )


def test_manager_checker_recognizes_alconna_rule_and_group_ban_notice():
    """manager/checker.py 的限流识别 AlconnaRule，并对非 MESSAGE 静默放行，同时保留自身禁言告警。"""
    from amrita.plugins.manager import checker as checker_mod
    from amrita.plugins.manager.amrita import amrita_cmd

    # Alconna 命令应被限流规则识别
    env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=GROUP, id="-100999"),
        actor=Actor(platform="telegram", user_id="555"),
        self_id="tg_bot",
        adapter="telegram",
    )
    checker_mod.watch_group.clear()
    with patch.object(checker_mod, "is_lp_admin", AsyncMock(return_value=False)):
        # 第一次消耗令牌放行
        asyncio.run(checker_mod.run(amrita_cmd(), env))
        # 紧接着第二次触发限流
        with pytest.raises(IgnoredException):
            asyncio.run(checker_mod.run(amrita_cmd(), env))

    # META 事件静默放行
    hb = HeartbeatMetaEvent(
        time=1700000000,
        self_id=10000,
        post_type="meta_event",
        meta_event_type="heartbeat",
        status={"online": True, "good": True},
        interval=5000,
    )
    hb_env = Envelope(
        kind=META,
        scope=Scope(platform="qq", kind=PRIVATE, id="10000"),
        actor=Actor(platform="qq", user_id="10000"),
        raw=hb,
        self_id="10000",
        adapter="onebot11",
    )
    asyncio.run(checker_mod.run(amrita_cmd(), hb_env))

    # 群禁言通知命中 Bot 自身时通知管理员
    ban_event = GroupBanNoticeEvent(
        time=1700000000,
        self_id=10000,
        post_type="notice",
        notice_type="group_ban",
        sub_type="ban",
        group_id=123456,
        operator_id=999,
        user_id=10000,
        duration=120,
    )
    from amrita.platform.shim import envelope_from

    ban_env = envelope_from(ban_event, strict=True)
    with patch.object(checker_mod, "send_to_admin", AsyncMock()) as mock_admin:
        # 触发 on_notice 注册的 handler
        notice_handlers = [
            h.call
            for m in nonebot.get_plugin("manager").matcher  # type: ignore[union-attr]
            if m.type == "notice"
            for h in m.handlers
        ]
        assert notice_handlers
        for fn in notice_handlers:
            asyncio.run(fn(ban_env))
        mock_admin.assert_awaited_once()
        assert "被禁言了2.0分钟" in mock_admin.call_args.args[0]


def test_manager_send_to_routes_via_platform_sender():
    """send_to.group / send_to.user 经平台 Sender 投递到对应会话，不依赖 OneBot 专属 API。"""
    from amrita.plugins.manager import send as send_mod

    tg_bot = _FakeTelegramBot()
    tg_env = Envelope(
        kind=MESSAGE,
        scope=Scope(platform="telegram", kind=PRIVATE, id="77001"),
        actor=Actor(platform="telegram", user_id="77001"),
        self_id="tg_bot",
        adapter="telegram",
    )
    group_handler = send_mod.group.handlers[0].call
    asyncio.run(
        group_handler(
            tg_bot,
            tg_env,
            Match(result="-100888", available=True),
            Match(result=("hello", "tg"), available=True),
        )
    )
    assert tg_bot.calls
    assert tg_bot.calls[0][1]["chat_id"] == -100888

    # 参数不足时提示并返回 FinishedException
    user_handler = send_mod.user.handlers[0].call
    with (
        patch.object(
            send_mod.user, "finish", AsyncMock(side_effect=FinishedException)
        ) as mock_finish,
        pytest.raises(FinishedException),
    ):
        asyncio.run(
            user_handler(
                tg_bot,
                tg_env,
                Match(result="123", available=True),
                Match(result=(), available=False),
            )
        )
    mock_finish.assert_awaited_once()


def test_l4ab_modules_have_no_onebot_v11_imports():
    """L4A 与 L4B 迁移范围内的模块及已删除的 manager/event.py 不再耦合 onebot.v11。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert not (root / "amrita/plugins/manager/event.py").exists()
    targets = [
        "amrita/utils/send.py",
        "amrita/utils/admin.py",
        "amrita/plugins/chat/utils/admin.py",
        "amrita/plugins/menu/commands.py",
        "amrita/plugins/menu/utils.py",
        "amrita/plugins/manager/list_black.py",
        "amrita/plugins/manager/send.py",
        "amrita/plugins/manager/auto_clean.py",
        "amrita/plugins/manager/checker.py",
        "amrita/plugins/manager/black.py",
    ]
    for rel in targets:
        text = (root / rel).read_text(encoding="utf-8")
        assert "onebot.v11" not in text, f"{rel} still references onebot.v11"
        assert "from nonebot.adapters.onebot" not in text


def test_set_enable_handler_toggles_status_manager():
    """set_enable 命令支持查询与切换 StatusManager 状态。"""
    from amrita.plugins.manager import checker as checker_mod
    from amrita.plugins.manager.status_manager import StatusManager

    handler = checker_mod.set_enable_cmd.handlers[0].call
    sm = StatusManager()
    orig_disable = sm.is_disabled()
    orig_unready = sm.is_unready()
    try:
        with (
            patch.object(
                checker_mod.set_enable_cmd,
                "finish",
                AsyncMock(side_effect=FinishedException),
            ) as mock_finish,
            pytest.raises(FinishedException),
        ):
            asyncio.run(handler(Match(result="false", available=True)))
        assert sm.ready is False
        assert "已关闭" in mock_finish.call_args.args[0]

        with (
            patch.object(
                checker_mod.set_enable_cmd,
                "finish",
                AsyncMock(side_effect=FinishedException),
            ) as mock_finish,
            pytest.raises(FinishedException),
        ):
            asyncio.run(handler(Match(result="true", available=True)))
        assert sm.ready is True
        assert "已启用" in mock_finish.call_args.args[0]
    finally:
        sm.set_disable(orig_disable)
        sm.set_unready(orig_unready)
