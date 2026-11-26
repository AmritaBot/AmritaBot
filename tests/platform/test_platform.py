"""平台层验收测试：归一化、主键对拍、出站、DI、角色补全、多模态。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11.event import (
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.adapters.onebot.v11.message import Message, MessageSegment

from amrita.platform import identity, registry
from amrita.platform.dto import GROUP, MESSAGE, PRIVATE, UNKNOWN
from amrita.platform.impl.qq.milky import MilkyPort
from amrita.platform.impl.qq.onebot import OneBotPort


def _resolve_role(env, bot):
    """按 envelope.adapter 找到端口，再让端口去补全角色。"""
    port = registry.get_adapter(env.adapter) or registry.get(env.scope.platform)
    return asyncio.run(port.resolve_role(bot, env.scope, env.actor))


def make_onebot_group_event() -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=456,
        message=Message([MessageSegment.text("hi "), MessageSegment.at(999)]),
        raw_message="hi",
        font=0,
        sender={"user_id": 123, "nickname": "N", "card": "", "role": "admin"},
        to_me=True,
        group_id=789,
    )


def make_onebot_private_event() -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=1700000001,
        self_id=10000,
        post_type="message",
        sub_type="friend",
        user_id=123,
        message_type="private",
        message_id=457,
        message=Message([MessageSegment.text("hello")]),
        raw_message="hello",
        font=0,
        sender={"user_id": 123, "nickname": "N"},
        to_me=True,
    )


class _Segment:
    def __init__(self, seg_type: str, data: dict) -> None:
        self.type = seg_type
        self.data = data


class MilkyGroupEvent:
    __module__ = "nonebot.adapters.milky.event"

    def __init__(self) -> None:
        self.time = 1700000002
        self.self_id = 10000
        self.message = [
            _Segment("text", {"text": "hey "}),
            _Segment("mention", {"user_id": 456}),
        ]
        self.data = SimpleNamespace(
            message_scene="group",
            peer_id=789,
            sender_id=123,
            message_seq=55,
            sender_name="M",
        )

    def get_type(self) -> str:
        return "message"

    def get_user_id(self) -> str:
        return "123"

    @property
    def message_id(self) -> int:
        return 55


class MilkyFriendEvent(MilkyGroupEvent):
    __module__ = "nonebot.adapters.milky.event"

    def __init__(self) -> None:
        super().__init__()
        self.data.message_scene = "friend"
        self.data.peer_id = 123


class DuckOnlyMilkyEvent:
    """模块名不像 milky，只能靠形状识别的事件。"""

    def __init__(self) -> None:
        self.time = 1700000003
        self.self_id = 10000
        self.message = [_Segment("text", {"text": "shape"})]
        self.data = SimpleNamespace(message_scene="group", peer_id=789, sender_id=123)

    def get_type(self) -> str:
        return "message"


class FakeOneBotBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send_group_msg(self, **kwargs):
        self.calls.append(("send_group_msg", kwargs))
        return {"message_id": 321}

    async def send_private_msg(self, **kwargs):
        self.calls.append(("send_private_msg", kwargs))
        return {"message_id": 322}

    async def delete_msg(self, **kwargs):
        self.calls.append(("delete_msg", kwargs))

    async def send_group_poke(self, **kwargs):
        self.calls.append(("send_group_poke", kwargs))


class FakeMilkyBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send_group_message(self, **kwargs):
        self.calls.append(("send_group_message", kwargs))
        return SimpleNamespace(message_seq=901)

    async def send_private_message(self, **kwargs):
        self.calls.append(("send_private_message", kwargs))
        return SimpleNamespace(message_seq=902)

    async def recall_group_message(self, **kwargs):
        self.calls.append(("recall_group_message", kwargs))

    async def recall_private_message(self, **kwargs):
        self.calls.append(("recall_private_message", kwargs))

    async def send_group_nudge(self, **kwargs):
        self.calls.append(("send_group_nudge", kwargs))

    async def send_friend_nudge(self, **kwargs):
        self.calls.append(("send_friend_nudge", kwargs))


def test_onebot_group_envelope():
    port = OneBotPort()
    event = make_onebot_group_event()
    env = port.to_envelope(event)

    assert env.kind == MESSAGE
    assert env.scope.kind == GROUP
    assert env.scope.id == "789"
    assert env.actor.user_id == "123"
    assert env.actor.role == "admin"
    assert env.text == "hi "
    assert env.mention_ids == ("999",)
    assert env.raw is event
    assert env.dedupe_key == "qq:msg:456"


def test_onebot_private_envelope():
    env = OneBotPort().to_envelope(make_onebot_private_event())
    assert env.scope.kind == PRIVATE
    assert env.scope.id == "123"
    assert env.actor.role == "member"  # 平台未给角色时降级
    assert identity.uni_id(env.scope) == "QQPlatform_Private_123"


def test_milky_group_envelope():
    env = MilkyPort().to_envelope(MilkyGroupEvent())
    assert env.kind == MESSAGE
    assert env.scope.kind == GROUP
    assert env.scope.id == "789"
    assert env.actor.user_id == "123"
    assert env.text == "hey "
    assert env.mention_ids == ("456",)
    assert env.dedupe_key == "qq:msg:55"


def test_milky_shape_detection_without_module_name():
    env = MilkyPort().to_envelope(DuckOnlyMilkyEvent())
    assert env.scope.kind == GROUP
    assert env.text == "shape"


def test_both_adapters_share_uni_id():
    onebot_env = OneBotPort().to_envelope(make_onebot_group_event())
    milky_env = MilkyPort().to_envelope(MilkyGroupEvent())

    assert identity.uni_id(onebot_env.scope) == identity.uni_id(milky_env.scope)
    assert identity.uni_id(onebot_env.scope) == "QQPlatform_Group_789"


def test_uni_id_roundtrip():
    scope = identity.parse_uni_id("QQPlatform_Group_789")
    assert scope is not None
    assert (scope.platform, scope.kind, scope.id) == ("qq", GROUP, "789")
    assert identity.parse_uni_id("garbage") is None


def test_unknown_event_is_unknown_kind():
    class Weird:
        time = 1
        self_id = 1
        data = SimpleNamespace(whatever=True)

        def get_type(self) -> str:
            return "something_new"

    env = MilkyPort().to_envelope(Weird())
    assert env.kind == UNKNOWN


def test_registry_resolves_by_adapter():
    assert isinstance(registry.resolve(make_onebot_group_event()), OneBotPort)
    assert isinstance(registry.resolve(MilkyGroupEvent()), MilkyPort)
    assert registry.resolve(SimpleNamespace(no="shape")) is None
    assert registry.get("qq") is not None


def test_onebot_sender_group():
    bot = FakeOneBotBot()
    sender = OneBotPort().sender(
        bot, OneBotPort().to_envelope(make_onebot_group_event()).scope
    )
    assert {"text", "image", "at", "reply", "recall"} <= sender.capabilities

    async def run():
        assert await sender.send_text("ok") == "321"
        assert await sender.recall("321") is True

    asyncio.run(run())
    assert [name for name, _ in bot.calls] == ["send_group_msg", "delete_msg"]
    assert bot.calls[0][1]["group_id"] == 789


def test_onebot_sender_private_has_no_at():
    bot = FakeOneBotBot()
    scope = OneBotPort().to_envelope(make_onebot_private_event()).scope
    sender = OneBotPort().sender(bot, scope)
    assert not sender.supports("at")

    async def run():
        assert await sender.send_text("ok") == "322"

    asyncio.run(run())
    assert bot.calls[0][0] == "send_private_msg"
    assert bot.calls[0][1]["user_id"] == 123


def test_milky_sender_group():
    bot = FakeMilkyBot()
    scope = MilkyPort().to_envelope(MilkyGroupEvent()).scope
    sender = MilkyPort().sender(bot, scope)

    async def run():
        assert await sender.send_text("ok") == "901"
        assert await sender.recall("901") is True

    asyncio.run(run())
    assert [name for name, _ in bot.calls] == [
        "send_group_message",
        "recall_group_message",
    ]
    assert bot.calls[0][1]["group_id"] == 789


def test_milky_sender_parts_degrades_to_text_without_adapter():
    """adapter-milky 未安装时，纯文本发送仍应可用。"""
    bot = FakeMilkyBot()
    scope = MilkyPort().to_envelope(MilkyGroupEvent()).scope
    sender = MilkyPort().sender(bot, scope)

    async def run():
        from amrita.platform.dto import Part

        assert await sender.send_parts((Part(kind="text", value="hi"),)) == "901"

    asyncio.run(run())
    assert bot.calls[0][0] == "send_group_message"


def test_scope_requires_known_kind():
    from amrita.platform.dto import Scope

    with pytest.raises(ValueError, match="unsupported scope kind"):
        Scope(platform="qq", kind="guild", id="1")


def test_actor_coerces_user_id_to_str():
    from amrita.platform.dto import Actor

    actor = Actor(platform="qq", user_id=cast(str, 12345))
    assert actor.user_id == "12345"


def test_envelope_from_marks_adapter_and_does_not_hold_events():
    """不缓存：Envelope 持有 raw 的强引用，缓存会把每个事件都钉在内存里。"""
    import gc
    import weakref

    from amrita.platform import shim

    event = make_onebot_group_event()
    ref = weakref.ref(event)
    assert shim.envelope_from(event).adapter == "onebot11"
    assert shim.envelope_from(MilkyGroupEvent()).adapter == "milky"
    del event
    gc.collect()
    assert ref() is None


def test_envelope_from_non_strict_returns_none():
    from amrita.platform import shim

    assert shim.envelope_from(SimpleNamespace(foo=1), strict=False) is None
    with pytest.raises(shim.UnsupportedEvent):
        shim.envelope_from(SimpleNamespace(foo=1))


def test_port_sender_picks_implementation_by_adapter():
    from amrita.platform import shim
    from amrita.platform.impl.qq.milky import MilkySender
    from amrita.platform.impl.qq.onebot import OneBotSender

    onebot_env = shim.envelope_from(make_onebot_group_event())
    milky_env = shim.envelope_from(MilkyGroupEvent())
    onebot_port = registry.get_adapter("onebot11")
    milky_port = registry.get_adapter("milky")
    assert onebot_port is not None
    assert milky_port is not None

    assert isinstance(
        onebot_port.sender(FakeOneBotBot(), onebot_env.scope), OneBotSender
    )
    assert isinstance(milky_port.sender(FakeMilkyBot(), milky_env.scope), MilkySender)


def test_telegram_shaped_envelope_fields():
    """Telegram 需要的形状（话题、编辑、转发、媒体组、回调）必须能装下。"""
    from amrita.platform.dto import ACTION, EDIT, Actor, Envelope, Scope

    scope = Scope(platform="telegram", kind="group", id="-100123", thread="42")
    actor = Actor(
        platform="telegram",
        user_id="555",
        nickname="u",
        role="admin",
        is_bot=False,
        permissions=frozenset({"send_messages"}),
    )
    env = Envelope(
        kind=EDIT,
        scope=scope,
        actor=actor,
        ts=1700000000.0,
        message_id="9001",
        reply_to="8990",
        self_id="777",
        edited_ts=1700000010.0,
        provenance=Actor(platform="telegram", user_id="888"),
        batch_key="album-1",
    )
    assert env.scope.thread == "42"
    assert env.reply_to == "8990"
    assert env.is_forwarded is True
    assert env.actor.can("send_messages") is True
    assert env.actor.can("manage_chat") is False

    callback = Envelope(
        kind=ACTION, scope=scope, actor=actor, action="callback", message_id="9001"
    )
    assert callback.kind == ACTION
    assert callback.action == "callback"


def test_channel_scope_and_uni_id():
    from amrita.platform import identity
    from amrita.platform.dto import Actor, Envelope, Scope

    scope = Scope(platform="qq", kind="channel", id="chan-1")
    assert scope.is_group is True
    env = Envelope(kind="message", scope=scope, actor=Actor(platform="qq", user_id="1"))
    assert identity.uni_id(env.scope) == "QQPlatform_Channel_chan-1"


def test_thread_uni_id_is_opt_in():
    from amrita.platform import identity
    from amrita.platform.dto import Scope

    plain = Scope(platform="telegram", kind="group", id="-100123")
    topic = Scope(platform="telegram", kind="group", id="-100123", thread="42")
    # uni_id 不变，避免历史记录被拆分
    assert identity.uni_id(plain) == identity.uni_id(topic)
    # 需要分桶时显式使用
    assert identity.thread_uni_id(topic).endswith("#42")


def test_senders_satisfy_protocol():
    from amrita.platform.impl.qq.milky import MilkyPort
    from amrita.platform.impl.qq.onebot import OneBotPort
    from amrita.platform.ports import Sender

    env = OneBotPort().to_envelope(make_onebot_group_event())
    onebot_sender = OneBotPort().sender(FakeOneBotBot(), env.scope)
    milky_env = MilkyPort().to_envelope(MilkyGroupEvent())
    milky_sender = MilkyPort().sender(FakeMilkyBot(), milky_env.scope)

    assert isinstance(onebot_sender, Sender)
    assert isinstance(milky_sender, Sender)
    # 预留能力未实现，调用应安全降级而不是抛异常
    assert onebot_sender.supports("edit") is False
    assert milky_sender.supports("edit") is False


def test_provide_envelope_builds_envelope_per_call():
    from amrita.platform import di, shim

    event = make_onebot_group_event()
    first = asyncio.run(di.provide_envelope(event))
    second = asyncio.run(di.provide_envelope(event))
    assert first is not second
    assert first.scope == second.scope
    assert first.adapter == "onebot11"
    assert shim.envelope_from(event).scope == first.scope


def test_provide_envelope_rejects_unknown_event():
    from amrita.platform import di, shim

    class NotAnEvent:
        pass

    with pytest.raises(shim.UnsupportedEvent):
        asyncio.run(di.provide_envelope(cast(Event, NotAnEvent())))


def test_envelope_nb_dep_is_a_nonebot_depends():
    from nonebot.internal.params import DependsInner

    from amrita.platform import di

    meta = di.EnvelopeNBDep.__metadata__[0]
    assert isinstance(meta, DependsInner)
    assert meta.dependency is di.provide_envelope


def _real_milky_event():
    milky_event = pytest.importorskip("nonebot.adapters.milky.event")
    payload = {
        "time": 1700000000,
        "self_id": 10000,
        "data": {
            "message_scene": "group",
            "peer_id": 789,
            "message_seq": 55,
            "sender_id": 123,
            "time": 1700000000,
            "segments": [
                {"type": "text", "data": {"text": "hey "}},
                {"type": "mention", "data": {"user_id": 999}},
                {"type": "image", "data": {"resource_id": "res-1"}},
            ],
        },
    }
    return milky_event.MessageEvent.model_validate(payload).convert()


def test_milky_real_adapter_envelope():
    env = MilkyPort().to_envelope(_real_milky_event())
    assert env.adapter == "milky"
    assert env.scope.kind == GROUP
    assert env.scope.id == "789"
    assert env.message_id == "55"
    assert env.dedupe_key == "qq:msg:55"
    assert [p.kind for p in env.parts] == ["text", "at", "image"]
    assert env.text == "hey "
    assert identity.uni_id(env.scope) == "QQPlatform_Group_789"


def test_milky_real_adapter_send_builds_native_segments():
    from amrita.platform.dto import Part

    env = MilkyPort().to_envelope(_real_milky_event())

    class _Bot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[str]]] = []

        async def send_group_message(self, *, group_id, message):
            self.calls.append(
                ("send_group_message", [str(e) for e in message.to_elements()])
            )
            return type("R", (), {"message_seq": 901})()

        async def recall_group_message(self, *, group_id, message_seq):
            self.calls.append(("recall_group_message", [str(message_seq)]))

    bot = _Bot()
    sender = MilkyPort().sender(cast(Bot, bot), env.scope)

    async def run():
        assert await sender.send_text("收到", reply_to="55") == "901"
        assert (
            await sender.send_parts(
                [
                    Part(kind="text", value="图文 "),
                    Part(kind="image", value="https://x/y.png"),
                    Part(kind="at", value="999"),
                ]
            )
            == "901"
        )
        assert await sender.recall("901") is True

    asyncio.run(run())
    assert bot.calls[0][0] == "send_group_message"
    assert "reply" in bot.calls[0][1][0]
    assert any("mention" in element for element in bot.calls[1][1])


def _onebot_group_event_without_role():
    from nonebot.adapters.onebot.v11.event import GroupMessageEvent
    from nonebot.adapters.onebot.v11.message import Message, MessageSegment

    return GroupMessageEvent(
        time=1700000020,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=901,
        message=Message([MessageSegment.text("hi")]),
        raw_message="hi",
        font=0,
        sender={"user_id": 123, "nickname": "N"},
        to_me=False,
        group_id=789,
    )


class _RoleBot:
    def __init__(self, role: str | None, *, fail: bool = False) -> None:
        self.role = role
        self.fail = fail
        self.queried: list[tuple[int, int]] = []

    async def get_group_member_info(self, *, group_id, user_id, no_cache=False):
        if self.fail:
            raise RuntimeError("api down")
        self.queried.append((group_id, user_id))
        # onebot v11 的 get_group_member_info 返回 dict
        return {"role": self.role}


def test_onebot_role_resolved_lazily():
    env = OneBotPort().to_envelope(_onebot_group_event_without_role())
    assert env.actor.role_known is False
    assert env.actor.role == "member"

    bot = _RoleBot("admin")
    actor = _resolve_role(env, cast(Bot, bot))
    assert actor.role == "admin"
    assert actor.role_known is True
    assert bot.queried == [(789, 123)]


def test_onebot_role_kept_when_event_has_it():
    env = OneBotPort().to_envelope(make_onebot_group_event())
    assert env.actor.role_known is True

    bot = _RoleBot("owner")
    actor = _resolve_role(env, cast(Bot, bot))
    assert actor.role == "admin"  # 事件里的值优先
    assert bot.queried == []  # 没有多余请求


def test_role_query_failure_does_not_guess():
    env = OneBotPort().to_envelope(_onebot_group_event_without_role())
    actor = _resolve_role(env, cast(Bot, _RoleBot(None, fail=True)))
    assert actor.role == "member"
    assert actor.role_known is False


def test_milky_role_resolved_from_member_info():
    env = MilkyPort().to_envelope(_real_milky_event())
    assert env.actor.role_known is False

    class _MilkyRoleBot(_RoleBot):
        async def get_group_member_info(self, *, group_id, user_id, no_cache=False):
            self.queried.append((group_id, user_id))
            # milky 返回 Member 模型，走属性访问
            return type("Member", (), {"role": self.role})()

    bot = _MilkyRoleBot("owner")
    actor = _resolve_role(env, cast(Bot, bot))
    assert actor.role == "owner"
    assert actor.role_known is True


def test_uni_id_is_platform_aware():
    from amrita.platform import identity
    from amrita.platform.dto import Scope

    qq = identity.uni_id(Scope(platform="qq", kind="group", id="789"))
    tg = identity.uni_id(Scope(platform="telegram", kind="group", id="789"))
    assert qq == "QQPlatform_Group_789"
    assert tg == "TelegramPlatform_Group_789"
    assert qq != tg
    parsed = identity.parse_uni_id(tg)
    assert parsed is not None
    assert parsed.platform == "telegram"


def test_envelope_carries_self_id_and_reply():
    env = OneBotPort().to_envelope(make_onebot_group_event())
    assert env.self_id == "10000"
    assert env.actor.is_bot is False


def test_milky_all_mention_does_not_crash():
    from amrita.platform.dto import Part

    env = MilkyPort().to_envelope(_real_milky_event())
    sender = MilkyPort().sender(cast(Bot, FakeMilkyBot()), env.scope)
    built = sender._build_message([Part(kind="at", value="all")])
    assert built is not None


def _heartbeat_event():
    from nonebot.adapters.onebot.v11.event import HeartbeatMetaEvent

    return HeartbeatMetaEvent(
        time=1700000003,
        self_id=10000,
        post_type="meta_event",
        meta_event_type="heartbeat",
        status={"online": True, "good": True},
        interval=5000,
    )


def _lifecycle_event():
    from nonebot.adapters.onebot.v11.event import LifecycleMetaEvent

    return LifecycleMetaEvent(
        time=1700000004,
        self_id=10000,
        post_type="meta_event",
        meta_event_type="lifecycle",
        sub_type="connect",
    )


def test_onebot_meta_event_falls_back_to_self_id():
    from amrita.platform.dto import META

    for event in (_heartbeat_event(), _lifecycle_event()):
        env = OneBotPort().to_envelope(event)
        assert env.kind == META
        assert env.scope.kind == PRIVATE
        assert env.scope.id == "10000"
        assert env.actor.user_id == "10000"
        assert env.message_id == ""
