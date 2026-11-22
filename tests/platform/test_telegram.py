"""Telegram 平台层验收：入站归一、主键、出站能力、角色补全。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from nonebot.adapters import Bot

from amrita.platform import identity, registry
from amrita.platform.dto import (
    ACTION,
    CHANNEL,
    EDIT,
    GROUP,
    MESSAGE,
    REQUEST,
    Actor,
    Part,
    Scope,
)
from amrita.platform.telegram import TelegramPort

TELEGRAM_ROOT = "-1001234567890"


def _event(raw: dict[str, object]) -> object:
    pytest.importorskip("nonebot.adapters.telegram")
    from nonebot.adapters.telegram.event import Event

    return Event.parse_event(raw)


def _group_message(**extra: object) -> object:
    body: dict[str, object] = {
        "message_id": 55,
        "date": 1700000000,
        "chat": {"id": int(TELEGRAM_ROOT), "type": "supergroup", "title": "T"},
        "from": {"id": 777, "is_bot": False, "first_name": "Al", "username": "al"},
        "text": "hi",
    }
    body.update(extra)
    return _event({"update_id": 100, "message": body})


def test_group_topic_text_is_merged_with_entities():
    env = TelegramPort().to_envelope(
        _group_message(
            message_thread_id=12,
            is_topic_message=True,
            text="hi there",
            entities=[
                {"type": "bold", "offset": 0, "length": 2},
                {
                    "type": "text_mention",
                    "offset": 3,
                    "length": 5,
                    "user": {"id": 888, "is_bot": False, "first_name": "Bo"},
                },
            ],
        )
    )

    assert env.kind == MESSAGE
    assert env.scope.kind == GROUP
    assert env.scope.id == TELEGRAM_ROOT
    assert env.scope.thread == "12"
    # 实体被切成多段，但正文必须完整拼回来
    assert env.text == "hi there"
    assert [part.kind for part in env.parts] == ["text"]
    entities = env.parts[0].meta["entities"]
    assert isinstance(entities, list)
    assert [item["type"] for item in entities] == ["bold", "text_mention"]
    assert entities[1]["offset"] == 3
    assert identity.uni_id(env.scope) == f"TelegramPlatform_Group_{TELEGRAM_ROOT}"
    # 话题不并入主键，只有显式分桶才带 #
    assert identity.thread_uni_id(env.scope).endswith("#12")


def test_private_message_scope_and_actor():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 101,
                "message": {
                    "message_id": 8,
                    "date": 1700000300,
                    "chat": {"id": 5, "type": "private", "first_name": "P"},
                    "from": {"id": 5, "is_bot": False, "first_name": "P"},
                    "text": "hello",
                },
            }
        )
    )

    assert env.scope.kind == "private"
    assert env.scope.id == "5"
    assert env.actor.user_id == "5"
    assert env.actor.nickname == "P"
    assert env.actor.role_known is False
    assert identity.uni_id(env.scope) == "TelegramPlatform_Private_5"


def test_channel_post_uses_channel_scope_and_has_no_reply():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 102,
                "channel_post": {
                    "message_id": 7,
                    "date": 1700000200,
                    "chat": {"id": -1007, "type": "channel", "title": "Ch"},
                    "sender_chat": {"id": -1007, "type": "channel", "title": "Ch"},
                    "text": "post",
                },
            }
        )
    )

    assert env.scope.kind == CHANNEL
    assert env.actor.user_id == "-1007"
    assert env.actor.nickname == "Ch"
    assert identity.uni_id(env.scope) == "TelegramPlatform_Channel_-1007"

    sender = TelegramPort().sender(cast(Bot, object()), env.scope)
    assert "reply" not in sender.capabilities


def test_edited_message_keeps_message_id_and_marks_edit_time():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 103,
                "edited_message": {
                    "message_id": 10,
                    "date": 1700000500,
                    "chat": {"id": int(TELEGRAM_ROOT), "type": "supergroup"},
                    "from": {"id": 6, "is_bot": False, "first_name": "F"},
                    "text": "edited",
                    "edit_date": 1700000600,
                },
            }
        )
    )

    assert env.kind == EDIT
    assert env.message_id == "10"
    assert env.edited_ts == 1700000600.0
    # 编辑时间只有秒级精度，再带上 update_id 才能区分同一秒内的两次编辑
    assert env.dedupe_key == f"telegram:edit:{TELEGRAM_ROOT}:10:1700000600:103"


def test_callback_query_is_action_not_message():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 104,
                "callback_query": {
                    "id": "cb1",
                    "from": {"id": 9, "is_bot": False, "first_name": "C"},
                    "chat_instance": "x",
                    "data": "btn1",
                },
            }
        )
    )

    assert env.kind == ACTION
    assert env.action == "callback"
    assert env.parts == (Part(kind="callback_data", value="btn1"),)
    assert env.scope.kind == "private"


def test_join_request_kind():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 105,
                "chat_join_request": {
                    "chat": {"id": -1009, "type": "supergroup", "title": "G"},
                    "from": {"id": 9, "is_bot": False, "first_name": "C"},
                    "user_chat_id": 9,
                    "date": 1700000100,
                },
            }
        )
    )

    assert env.kind == REQUEST
    assert env.scope.kind == GROUP


def test_photo_and_caption_become_text_plus_image():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 106,
                "message": {
                    "message_id": 9,
                    "date": 1700000400,
                    "chat": {"id": int(TELEGRAM_ROOT), "type": "supergroup"},
                    "from": {"id": 6, "is_bot": False, "first_name": "F"},
                    "photo": [
                        {
                            "file_id": "small",
                            "file_unique_id": "u1",
                            "width": 90,
                            "height": 90,
                        },
                        {
                            "file_id": "big",
                            "file_unique_id": "u2",
                            "width": 800,
                            "height": 800,
                        },
                    ],
                    "caption": "cap",
                    "media_group_id": "ag1",
                },
            }
        )
    )

    assert [part.kind for part in env.parts] == ["text", "image"]
    assert env.text == "cap"
    # 多尺寸时取最后一档（Telegram 按由小到大排列）
    assert env.parts[1].value == "big"
    # 适配器只保留了 file_id，没有 file_unique_id，meta 里如实照抄原始段
    assert env.parts[1].meta["data"] == {"file": "big"}
    assert env.batch_key == "ag1"


def test_forward_origin_becomes_provenance():
    env = TelegramPort().to_envelope(
        _group_message(forward_from={"id": 42, "is_bot": False, "first_name": "Orig"})
    )

    assert env.provenance is not None
    assert env.provenance.user_id == "42"
    assert env.is_forwarded is True


def test_dedupe_key_includes_chat():
    port = TelegramPort()
    left = port.to_envelope(_group_message(message_id=55))
    right = port.to_envelope(
        _group_message(
            message_id=55,
            chat={"id": -1009999, "type": "supergroup", "title": "Other"},
        )
    )

    # message_id 只在单个 chat 内唯一，跨群不能撞键
    assert left.dedupe_key != right.dedupe_key
    assert left.dedupe_key == f"telegram:msg:{TELEGRAM_ROOT}:55"


def test_shape_detection_without_adapter_module_name():
    class _Segment:
        type = "text"

        def __init__(self) -> None:
            self.data = {"text": "shape"}
            self.cls = SimpleNamespace(type="supergroup", id=-1005)

        def is_text(self) -> bool:
            return True

    class ShapeEvent:
        """模块名不像 telegram，只能靠 chat.type 识别。"""

        def __init__(self) -> None:
            self.chat = SimpleNamespace(type="supergroup", id=-1005)
            self.date = 1700000000
            self.message_id = 3
            self.from_ = SimpleNamespace(id=77, is_bot=False, first_name="S")
            self.message = [_Segment()]

        def get_type(self) -> str:
            return "message"

        def get_event_name(self) -> str:
            return "message.group"

    env = TelegramPort().to_envelope(ShapeEvent())
    assert env.scope.kind == GROUP
    assert env.text == "shape"


def test_registry_separates_platforms():
    from nonebot.adapters.onebot.v11.event import GroupMessageEvent
    from nonebot.adapters.onebot.v11.message import Message

    onebot_event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=1,
        message=Message("x"),
        raw_message="x",
        font=0,
        sender={"user_id": 123},
        to_me=False,
        group_id=789,
    )

    assert TelegramPort().match(onebot_event) is False
    assert isinstance(registry.resolve(_group_message()), TelegramPort)
    assert registry.get("telegram") is not None


class _FakeTgBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.messages: list[object] = []

    async def send_to(self, chat_id, message, message_thread_id=None):
        self.calls.append(
            ("send_to", {"chat_id": chat_id, "thread": message_thread_id})
        )
        self.messages.append(message)
        self.last_message = message
        return SimpleNamespace(message_id=4321)

    async def send_message(self, *, chat_id, text, message_thread_id=None):
        self.calls.append(("send_message", {"chat_id": chat_id, "text": text}))
        return SimpleNamespace(message_id=4322)

    async def delete_message(self, *, chat_id, message_id):
        self.calls.append(("delete_message", {"chat_id": chat_id, "id": message_id}))
        return True

    async def edit_message_text(self, *, text, chat_id, message_id):
        self.calls.append(("edit_message_text", {"text": text, "id": message_id}))
        return True

    async def send_chat_action(self, *, chat_id, action, message_thread_id=None):
        self.calls.append(("send_chat_action", {"chat_id": chat_id, "action": action}))
        return True

    async def get_chat_member(self, *, chat_id, user_id):
        self.calls.append(("get_chat_member", {"chat_id": chat_id, "user_id": user_id}))
        return self.member


def _sender(scope: Scope) -> tuple[TelegramPort, _FakeTgBot, object]:
    bot = _FakeTgBot()
    sender = TelegramPort().sender(cast(Bot, bot), scope)
    return TelegramPort(), bot, sender


def test_sender_text_with_reply_and_thread():
    pytest.importorskip("nonebot.adapters.telegram")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT, thread="12")
    _, bot, sender = _sender(scope)

    async def run() -> str:
        return await sender.send_text("收到", reply_to="54")

    assert asyncio.run(run()) == "4321"
    assert bot.calls[0] == ("send_to", {"chat_id": int(TELEGRAM_ROOT), "thread": 12})
    segments = [(seg.type, seg.data) for seg in bot.last_message]
    assert segments[0][0] == "reply"
    assert segments[0][1]["message_id"] == 54
    assert segments[1] == ("text", {"text": "收到"})


def test_sender_parts_maps_media_and_degrades_mention():
    pytest.importorskip("nonebot.adapters.telegram")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)
    _, bot, sender = _sender(scope)

    async def run() -> str:
        return await sender.send_parts(
            [
                Part(kind="text", value="看图 "),
                Part(kind="image", value="FILE_ID"),
                Part(kind="at", value="alice"),
            ]
        )

    assert asyncio.run(run()) == "4321"
    segments = [(seg.type, seg.data) for seg in bot.last_message]
    assert segments[1] == ("photo", {"file": "FILE_ID"})
    # Telegram 不能按 id @，只能降级成文本
    assert segments[2] == ("text", {"text": "@alice "})


def test_sender_capabilities_and_recall_edit_typing():
    pytest.importorskip("nonebot.adapters.telegram")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT, thread="12")
    _, bot, sender = _sender(scope)
    assert {"text", "image", "reply", "recall", "edit", "typing", "thread"} <= set(
        sender.capabilities
    )

    async def run() -> tuple[bool, bool, bool]:
        recalled = await sender.recall("4321")
        edited = await sender.edit("4321", [Part(kind="text", value="改过")])
        media_edit = await sender.edit("4321", [Part(kind="image", value="x")])
        await sender.typing()
        return recalled, edited, media_edit

    recalled, edited, media_edit = asyncio.run(run())
    assert recalled is True
    assert edited is True
    # 带媒体的编辑要换 API，这里如实失败而不是假装成功
    assert media_edit is False
    assert ("edit_message_text", {"text": "改过", "id": 4321}) in bot.calls
    assert (
        "send_chat_action",
        {"chat_id": int(TELEGRAM_ROOT), "action": "typing"},
    ) in (bot.calls)


def test_recall_failure_is_swallowed():
    pytest.importorskip("nonebot.adapters.telegram")

    class _BrokenBot(_FakeTgBot):
        async def delete_message(self, *, chat_id, message_id):
            raise RuntimeError("too old")

    sender = TelegramPort().sender(
        cast(Bot, _BrokenBot()), Scope(platform="telegram", kind=GROUP, id="1")
    )
    assert asyncio.run(sender.recall("1")) is False


def _role_actor() -> Actor:
    return Actor(platform="telegram", user_id="777")


def test_role_resolved_from_chat_member():
    pytest.importorskip("nonebot.adapters.telegram")
    bot = _FakeTgBot()
    bot.member = SimpleNamespace(
        status="administrator",
        can_delete_messages=True,
        can_invite_users=True,
        can_send_messages=True,
    )
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)

    actor = asyncio.run(
        TelegramPort().resolve_role(cast(Bot, bot), scope, _role_actor())
    )
    assert actor.role == "admin"
    assert actor.role_known is True
    assert "manage_messages" in actor.permissions
    assert "manage_chat" in actor.permissions
    assert bot.calls[0] == (
        "get_chat_member",
        {"chat_id": int(TELEGRAM_ROOT), "user_id": 777},
    )


def test_restricted_member_permissions():
    pytest.importorskip("nonebot.adapters.telegram")
    bot = _FakeTgBot()
    bot.member = SimpleNamespace(
        status="restricted",
        is_member=True,
        can_send_messages=False,
        can_delete_messages=False,
    )
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)

    actor = asyncio.run(
        TelegramPort().resolve_role(cast(Bot, bot), scope, _role_actor())
    )
    assert actor.role == "member"
    assert actor.role_known is True
    assert "restricted" in actor.permissions
    assert "send_messages" not in actor.permissions


def test_left_member_keeps_role_unknown():
    pytest.importorskip("nonebot.adapters.telegram")
    bot = _FakeTgBot()
    bot.member = SimpleNamespace(status="kicked")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)

    actor = asyncio.run(
        TelegramPort().resolve_role(cast(Bot, bot), scope, _role_actor())
    )
    assert actor.role_known is False


def test_role_query_failure_does_not_guess():
    pytest.importorskip("nonebot.adapters.telegram")

    class _FailingBot(_FakeTgBot):
        async def get_chat_member(self, *, chat_id, user_id):
            raise RuntimeError("api down")

    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)
    actor = asyncio.run(
        TelegramPort().resolve_role(cast(Bot, _FailingBot()), scope, _role_actor())
    )
    assert actor.role_known is False
    assert actor.role == "member"


def test_private_chat_skips_role_query():
    pytest.importorskip("nonebot.adapters.telegram")
    bot = _FakeTgBot()
    scope = Scope(platform="telegram", kind="private", id="777")

    actor = asyncio.run(
        TelegramPort().resolve_role(cast(Bot, bot), scope, _role_actor())
    )
    assert actor.role_known is False
    assert bot.calls == []


def _block_adapter(monkeypatch) -> None:
    """模拟没装 telegram 适配器：import 直接失败，不能靠缓存蒙混过关。"""
    from amrita.platform.telegram import api as tg_api

    def _missing(name: str) -> None:
        raise ImportError(f"blocked: {name}")

    monkeypatch.setattr(tg_api, "import_module", _missing)
    monkeypatch.setattr(tg_api, "_loaded", False)
    monkeypatch.setattr(tg_api, "_api", None)


def test_load_api_returns_none_without_adapter(monkeypatch):
    from amrita.platform.telegram import api as tg_api

    _block_adapter(monkeypatch)
    assert tg_api.load_api() is None


def test_sender_falls_back_to_plain_text_without_adapter(monkeypatch):
    _block_adapter(monkeypatch)
    bot = _FakeTgBot()
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT, thread="12")
    sender = TelegramPort().sender(cast(Bot, bot), scope)

    async def run() -> str:
        return await sender.send_text("纯文本")

    assert asyncio.run(run()) == "4322"
    assert bot.calls == [
        ("send_message", {"chat_id": int(TELEGRAM_ROOT), "text": "纯文本"})
    ]


def test_envelope_from_registers_telegram_adapter():
    from amrita.platform import shim

    env = shim.envelope_from(_group_message())
    assert env.adapter == "telegram"
    assert registry.get_adapter("telegram") is not None
    assert shim.uni_id_of(env).startswith("TelegramPlatform_Group_")
    assert shim.sender_of(env, cast(Bot, _FakeTgBot())).capabilities


def test_channel_uni_id_roundtrip():
    scope = identity.parse_uni_id("TelegramPlatform_Channel_-1007")
    assert scope is not None
    assert (scope.platform, scope.kind, scope.id) == ("telegram", CHANNEL, "-1007")


def test_callback_scope_falls_back_to_message_chat():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 107,
                "callback_query": {
                    "id": "cb2",
                    "from": {"id": 9, "is_bot": False, "first_name": "C"},
                    "chat_instance": "x",
                    "data": "btn2",
                    "message": {
                        "message_id": 31,
                        "date": 1700000700,
                        "chat": {"id": -1008, "type": "supergroup", "title": "G"},
                        "text": "带按钮的消息",
                    },
                },
            }
        )
    )

    # 顶层没有 chat，但按钮挂在群里，回复必须回到群里而不是发起人私聊
    assert env.scope.kind == GROUP
    assert env.scope.id == "-1008"


def test_sender_chat_wins_over_placeholder_from_user():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 108,
                "message": {
                    "message_id": 32,
                    "date": 1700000800,
                    "chat": {"id": -1008, "type": "supergroup", "title": "G"},
                    "from": {"id": 1087968824, "is_bot": True, "first_name": "Group"},
                    "sender_chat": {"id": -1008, "type": "supergroup", "title": "G"},
                    "text": "匿名管理员发言",
                },
            }
        )
    )

    # 匿名管理员会带一个代发账号，主体应该是群本身
    assert env.actor.user_id == "-1008"
    assert env.actor.nickname == "G"


def test_forward_origin_is_read_from_raw_update():
    env = TelegramPort().to_envelope(
        _event(
            {
                "update_id": 109,
                "message": {
                    "message_id": 33,
                    "date": 1700000900,
                    "chat": {"id": int(TELEGRAM_ROOT), "type": "supergroup"},
                    "from": {"id": 6, "is_bot": False, "first_name": "F"},
                    "text": "转发的",
                    "forward_origin": {
                        "type": "user",
                        "date": 1700000000,
                        "sender_user": {
                            "id": 4242,
                            "is_bot": False,
                            "first_name": "Orig",
                        },
                    },
                },
            }
        )
    )

    assert env.provenance is not None
    assert env.provenance.user_id == "4242"
    assert env.provenance.nickname == "Orig"


def test_callback_dedupe_keys_are_distinct():
    port = TelegramPort()

    def _cb(cb_id: str, update_id: int) -> object:
        return _event(
            {
                "update_id": update_id,
                "callback_query": {
                    "id": cb_id,
                    "from": {"id": 9, "is_bot": False, "first_name": "C"},
                    "chat_instance": "x",
                    "data": "btn",
                },
            }
        )

    first = port.to_envelope(_cb("cb-a", 110))
    second = port.to_envelope(_cb("cb-b", 111))
    # 同一个用户同一秒点了两次同样的按钮，仍然要算两条事件
    assert first.dedupe_key != second.dedupe_key


def test_restricted_media_permission_marks_restricted():
    pytest.importorskip("nonebot.adapters.telegram")
    bot = _FakeTgBot()
    bot.member = SimpleNamespace(
        status="restricted",
        is_member=True,
        can_send_messages=True,
        can_send_photos=False,
        can_send_audios=True,
        can_send_documents=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_delete_messages=False,
    )
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)

    actor = asyncio.run(
        TelegramPort().resolve_role(cast(Bot, bot), scope, _role_actor())
    )
    assert "send_messages" in actor.permissions
    # 能发文字但发不了图，同样算受限
    assert "restricted" in actor.permissions


def test_long_text_is_split_into_multiple_messages():
    pytest.importorskip("nonebot.adapters.telegram")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)
    _, bot, sender = _sender(scope)
    long_text = "\n".join("行" * 120 for _ in range(60))

    async def run() -> str:
        return await sender.send_text(long_text, reply_to="54")

    assert asyncio.run(run()) == "4321"
    sends = [call for call in bot.calls if call[0] == "send_to"]
    assert len(sends) > 1
    # 引用只挂在第一条，后续分片不能重复回复同一条消息
    first_segments = [(seg.type, seg.data) for seg in bot.messages[0]]
    assert first_segments[0][0] == "reply"
    rest_segments = [(seg.type, seg.data) for seg in bot.messages[1]]
    assert rest_segments[0][0] == "text"


def test_sticker_is_sent_in_its_own_message():
    pytest.importorskip("nonebot.adapters.telegram")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)
    _, bot, sender = _sender(scope)

    async def run() -> str:
        return await sender.send_parts(
            [Part(kind="text", value="贴纸来了"), Part(kind="sticker", value="STK")]
        )

    asyncio.run(run())
    sends = [call for call in bot.calls if call[0] == "send_to"]
    assert len(sends) == 2
    assert [seg.type for seg in bot.messages[0]] == ["text"]
    assert [seg.type for seg in bot.messages[1]] == ["sticker"]


def test_numeric_mention_is_not_faked():
    pytest.importorskip("nonebot.adapters.telegram")
    scope = Scope(platform="telegram", kind=GROUP, id=TELEGRAM_ROOT)
    _, bot, sender = _sender(scope)

    async def run() -> str:
        return await sender.send_parts(
            [Part(kind="text", value="hi "), Part(kind="at", value="888")]
        )

    asyncio.run(run())
    segments = [(seg.type, seg.data) for seg in bot.messages[0]]
    # 没有 username 就发不出真正的提及，宁可丢掉也不发假 @888
    assert segments == [("text", {"text": "hi "})]
