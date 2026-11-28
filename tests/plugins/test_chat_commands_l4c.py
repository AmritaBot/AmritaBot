"""验证 L4C 迁移：chat 管理命令 Alconna 路由、群管权限解耦与 8 个管理命令执行链路。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nonebot
import pytest
from nonebot.exception import FinishedException
from nonebot_plugin_alconna import AlconnaRule, CommandResult
from pytz import utc

from amrita.platform.dto import (
    GROUP,
    MESSAGE,
    PRIVATE,
    Actor,
    Envelope,
    Part,
    Scope,
)
from amrita.platform.ports import CAP_AT, CAP_TEXT


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
    if nonebot.get_plugin("chat") is None:
        nonebot.load_plugin("amrita.plugins.chat")


class _FakeMatcher:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, msg: object) -> None:
        self.sent.append(msg)

    async def finish(self, msg: object = "") -> None:
        if msg != "":
            self.sent.append(msg)
        raise FinishedException


def _group_env(
    *,
    platform: str = "qq",
    adapter: str = "onebot.v11",
    group_id: str = "10001",
    user_id: str = "20002",
    role: str = "",
    role_known: bool = False,
) -> Envelope:
    return Envelope(
        adapter=adapter,
        kind=MESSAGE,
        scope=Scope(platform=platform, kind=GROUP, id=group_id),
        actor=Actor(
            platform=platform,
            user_id=user_id,
            nickname="tester",
            role=role,
            role_known=role_known,
        ),
        message_id="msg-1",
        self_id="10000",
    )


def _private_env(
    *,
    platform: str = "qq",
    adapter: str = "onebot.v11",
    user_id: str = "20002",
) -> Envelope:
    return Envelope(
        adapter=adapter,
        kind=MESSAGE,
        scope=Scope(platform=platform, kind=PRIVATE, id=user_id),
        actor=Actor(platform=platform, user_id=user_id, nickname="tester"),
        message_id="msg-2",
        self_id="10000",
    )


def _cmd_result(command: str, text: str) -> CommandResult:
    from amrita.plugins.chat.matcher_manager import COMMAND_MATCHERS

    matcher = COMMAND_MATCHERS[command]
    alc = matcher._rule.command()
    arp = alc.parse(text)
    assert arp.matched, f"{text!r} failed to match {command!r}"
    return CommandResult(source=alc, result=arp)


def test_l4c_command_matchers_registered_as_alconna_with_menu_state():
    """8 条 chat 管理命令均通过 on_alconna(use_cmd_start=True) 注册且保留菜单元数据。"""
    from amrita.plugins.chat.matcher_manager import COMMAND_MATCHERS
    from amrita.plugins.menu.models import MatcherData

    expected = {
        "model",
        "prompt",
        "session",
        "chat",
        "debug",
        "insights",
        "mcp",
        "chatobj",
    }
    assert set(COMMAND_MATCHERS.keys()) == expected

    for name, matcher in COMMAND_MATCHERS.items():
        assert any(
            isinstance(checker.call, AlconnaRule) for checker in matcher.rule.checkers
        ), f"{name} missing AlconnaRule"
        data = MatcherData.model_validate(matcher._default_state)
        assert data.name
        assert data.usage

    # 抽检前缀、别名与自由参数（含 -h/-d/-t/多行文本）解析
    cases = [
        ("model", "/model test demo -d -t 15", "test demo -d -t 15"),
        ("model", "/模型 info", "info"),
        ("prompt", "/prompt set 你好\n第二行 -h --help", "set 你好\n第二行 -h --help"),
        ("session", "/session compact force", "compact force"),
        ("session", "/会话 list", "list"),
        ("chat", "/chat auto on", "auto on"),
        ("chat", "/聊天开关", ""),
        ("debug", "/debug status", "status"),
        ("insights", "/insights top5", "top5"),
        ("insights", "/今日用量", ""),
        ("mcp", "/mcp stats -d", "stats -d"),
        ("chatobj", "/chatobj kill abcd", "kill abcd"),
    ]
    from amrita.plugins.chat.handlers._alconna import extract_raw_args

    for cmd, text, expected_args in cases:
        res = _cmd_result(cmd, text)
        assert extract_raw_args(res) == expected_args

    # 不误匹配前缀粘连的词（原 force_whitespace 语义）
    assert not COMMAND_MATCHERS["session"]._rule.command().parse("/sessions").matched
    assert not COMMAND_MATCHERS["model"]._rule.command().parse("/models").matched


def test_l4c_check_rule_group_admin_uses_envelope_and_resolve_role():
    """is_group_admin / is_group_admin_if_is_in_group 走 Envelope + port.resolve_role。"""
    from amrita.plugins.chat.check_rule import (
        is_group_admin,
        is_group_admin_if_is_in_group,
    )

    async def _run() -> None:
        # 1. 已知群管理员直接放行
        admin_env = _group_env(role="admin", role_known=True)
        assert await is_group_admin(admin_env, None) is True

        # 2. 未知角色通过 port.resolve_role 补全为 owner -> True
        unknown_env = _group_env(role="", role_known=False)
        fake_port = SimpleNamespace(
            resolve_role=AsyncMock(
                return_value=Actor(
                    platform="qq",
                    user_id="20002",
                    nickname="tester",
                    role="owner",
                    role_known=True,
                )
            )
        )
        with (
            patch(
                "amrita.plugins.chat.check_rule.registry.get_adapter",
                return_value=fake_port,
            ),
            patch(
                "amrita.plugins.chat.check_rule.is_lp_admin_for",
                AsyncMock(return_value=False),
            ),
        ):
            assert await is_group_admin(unknown_env, SimpleNamespace()) is True  # type: ignore[arg-type]
        fake_port.resolve_role.assert_awaited_once()

        # 3. 普通群成员且非 lp 管理员 -> False
        member_env = _group_env(role="member", role_known=True)
        with patch(
            "amrita.plugins.chat.check_rule.is_lp_admin_for",
            AsyncMock(return_value=False),
        ):
            assert await is_group_admin(member_env, None) is False
            assert await is_group_admin_if_is_in_group(member_env, None) is False

        # 4. 私聊下 is_group_admin_if_is_in_group 直接 True；is_group_admin False
        priv_env = _private_env()
        assert await is_group_admin(priv_env, None) is False
        assert await is_group_admin_if_is_in_group(priv_env, None) is True

        # 5. None（meta 事件）静默 False
        assert await is_group_admin(None, None) is False
        assert await is_group_admin_if_is_in_group(None, None) is False

    asyncio.run(_run())


def test_l4c_chat_switch_debug_and_prompt_handlers():
    """chat_switch / debug_switchs / prompt 走 EnvelopeNBDep + AlconnaResult 正常工作。"""
    import importlib

    chat_switch_mod = importlib.import_module(
        "amrita.plugins.chat.handlers.chat_switch"
    )
    debug_mod = importlib.import_module("amrita.plugins.chat.handlers.debug_switchs")
    prompt_mod = importlib.import_module("amrita.plugins.chat.handlers.prompt")

    async def _run() -> None:
        # chat_switch（支持 Telegram 负数群 ID 的 Scope）
        tg_group_env = _group_env(
            platform="telegram", adapter="telegram", group_id="-10012345"
        )
        gc = SimpleNamespace(enable=True, autoreply=False)
        fake_repo = SimpleNamespace(
            get_group_config=AsyncMock(return_value=gc),
            update_group_config=AsyncMock(),
        )
        matcher = _FakeMatcher()
        with patch.object(
            chat_switch_mod,
            "CachedGroupDataRepository",
            return_value=fake_repo,
        ):
            await chat_switch_mod.chat(
                tg_group_env,
                matcher,  # type: ignore[arg-type]
                _cmd_result("chat", "/chat off"),
            )
        assert gc.enable is False
        fake_repo.get_group_config.assert_awaited_once_with(tg_group_env.scope)
        assert any("禁用聊天功能" in str(m) for m in matcher.sent)

        # debug_switchs
        dbg_matcher = _FakeMatcher()
        with pytest.raises(FinishedException):
            await debug_mod.debug_switchs(
                dbg_matcher,  # type: ignore[arg-type]
                _cmd_result("debug", "/debug status"),
            )
        assert any("调试模式" in str(m) for m in dbg_matcher.sent)

        # prompt set 保留多行与空格
        mem_data = SimpleNamespace(extra_prompt="")
        fake_user_repo = SimpleNamespace(get_memory=AsyncMock(return_value=mem_data))
        p_matcher = _FakeMatcher()
        fake_prompt_cfg = SimpleNamespace(
            config=SimpleNamespace(function=SimpleNamespace(allow_custom_prompt=True))
        )
        with (
            patch.object(prompt_mod, "config_manager", fake_prompt_cfg),
            patch.object(
                prompt_mod,
                "CachedUserDataRepository",
                return_value=fake_user_repo,
            ),
            patch.object(
                prompt_mod,
                "update_memory",
                AsyncMock(),
            ) as mock_update,
        ):
            await prompt_mod.prompt(
                tg_group_env,
                p_matcher,  # type: ignore[arg-type]
                _cmd_result("prompt", "/prompt set 第一行\n第二行"),
            )
        assert mem_data.extra_prompt == "第一行\n第二行"
        mock_update.assert_awaited_once()
        fake_user_repo.get_memory.assert_awaited_once_with(
            "TelegramPlatform_Group_-10012345"
        )

    asyncio.run(_run())


def test_l4c_insights_mcp_chatobj_and_session_handlers():
    """insights / mcp / chatobj / session 在非 OneBot 平台 Envelope 下均无 v11 耦合。"""
    import importlib

    insights_mod = importlib.import_module("amrita.plugins.chat.handlers.insights")
    from amrita.plugins.chat.handlers.chatobj import (
        chatobj_manage,
        format_chat_object_info,
    )
    from amrita.plugins.chat.handlers.mcp import mcp_command
    from amrita.plugins.chat.handlers.session_cmd import session as session_handler

    async def _run() -> None:
        # 1. insights 群聊带 CAP_AT -> sender.send_parts([at, text])
        env_grp = _group_env(
            platform="qq", adapter="milky", group_id="8888", user_id="9999"
        )
        fake_meta = SimpleNamespace(called_count=3, tokens_input=100, tokens_output=50)
        fake_sender = SimpleNamespace(
            capabilities=frozenset({CAP_TEXT, CAP_AT}),
            supports=lambda cap: cap in {CAP_TEXT, CAP_AT},
            send_parts=AsyncMock(),
        )
        ins_matcher = _FakeMatcher()
        fake_insights_cfg = SimpleNamespace(
            config=SimpleNamespace(
                usage_limit=SimpleNamespace(
                    user_daily_limit=100,
                    user_daily_token_limit=10000,
                    group_daily_limit=200,
                    group_daily_token_limit=20000,
                    enable_usage_limit=True,
                )
            )
        )
        with (
            patch.object(insights_mod, "config_manager", fake_insights_cfg),
            patch.object(
                insights_mod,
                "CachedUserDataRepository",
                return_value=SimpleNamespace(
                    get_metadata=AsyncMock(return_value=fake_meta)
                ),
            ),
            patch.object(
                insights_mod,
                "is_bot_admin",
                AsyncMock(return_value=False),
            ),
            patch.object(
                insights_mod,
                "has_any_permission",
                AsyncMock(return_value=False),
            ),
            patch.object(
                insights_mod,
                "resolve_sender",
                return_value=fake_sender,
            ),
        ):
            with pytest.raises(FinishedException):
                await insights_mod.insights(
                    SimpleNamespace(self_id="10000"),  # type: ignore[arg-type]
                    env_grp,
                    ins_matcher,  # type: ignore[arg-type]
                    _cmd_result("insights", "/insights"),
                )
        fake_sender.send_parts.assert_awaited_once()
        sent_parts = fake_sender.send_parts.await_args.args[0]
        assert sent_parts[0] == Part(kind="at", value="9999")
        assert "群组使用次数为：3" in sent_parts[1].value

        # 2. mcp stats -d 在群聊拒绝，在私聊走 send_forward_msg(bot, env, ...)
        mcp_matcher = _FakeMatcher()
        with (
            patch("amrita.plugins.chat.handlers.mcp.list_states", return_value=[]),
            patch(
                "amrita.plugins.chat.handlers.mcp.ClientManager",
                return_value=SimpleNamespace(
                    name_to_clients={}, tools_remapping={}, clients=[]
                ),
            ),
        ):
            with pytest.raises(FinishedException):
                await mcp_command(
                    SimpleNamespace(self_id="10000"),  # type: ignore[arg-type]
                    env_grp,
                    mcp_matcher,  # type: ignore[arg-type]
                    _cmd_result("mcp", "/mcp stats -d"),
                )
        assert any("私聊" in str(m) for m in mcp_matcher.sent)

        env_priv = _private_env(platform="telegram", adapter="telegram", user_id="555")
        mcp_matcher2 = _FakeMatcher()
        with (
            patch("amrita.plugins.chat.handlers.mcp.list_states", return_value=[]),
            patch(
                "amrita.plugins.chat.handlers.mcp.ClientManager",
                return_value=SimpleNamespace(
                    name_to_clients={}, tools_remapping={}, clients=[]
                ),
            ),
            patch(
                "amrita.plugins.chat.handlers.mcp.send_forward_msg",
                AsyncMock(),
            ) as mock_fwd,
        ):
            await mcp_command(
                SimpleNamespace(self_id="10000"),  # type: ignore[arg-type]
                env_priv,
                mcp_matcher2,  # type: ignore[arg-type]
                _cmd_result("mcp", "/mcp stats -d"),
            )
        mock_fwd.assert_awaited_once()
        assert mock_fwd.await_args.args[1] is env_priv

        # 3. chatobj status 走 send_forward_msg 且 format_chat_object_info 兼容 Envelope
        now = datetime.now(tz=utc)
        fake_obj = SimpleNamespace(
            stream_id="abcdef1234567890",
            last_call=now,
            time=now,
            end_at=None,
            is_running=lambda: True,
            is_done=lambda: False,
            get_exception=lambda: None,
            _hook_kwargs={"amrita": {"event": env_priv}},
        )
        info = format_chat_object_info(fake_obj)  # type: ignore[arg-type]
        assert "TelegramPlatform_Private_555" in info
        assert "私聊" in info

        obj_matcher = _FakeMatcher()
        with (
            patch(
                "amrita.plugins.chat.handlers.chatobj.bot_chat_manager.get_objs",
                return_value=[fake_obj],
            ),
            patch(
                "amrita.plugins.chat.handlers.chatobj.send_forward_msg",
                AsyncMock(),
            ) as mock_obj_fwd,
        ):
            await chatobj_manage(
                SimpleNamespace(self_id="10000"),  # type: ignore[arg-type]
                env_priv,
                obj_matcher,  # type: ignore[arg-type]
                _cmd_result("chatobj", "/chatobj status"),
            )
        mock_obj_fwd.assert_awaited_once()
        assert mock_obj_fwd.await_args.args[1] is env_priv

        # 4. session clear 不带 confirm 时提示确认，且权限校验吃 Envelope
        sess_matcher = _FakeMatcher()
        with patch(
            "amrita.plugins.chat.handlers.session_cmd.is_group_admin_if_is_in_group",
            AsyncMock(return_value=True),
        ) as mock_perm:
            with pytest.raises(FinishedException):
                await session_handler(
                    SimpleNamespace(self_id="10000"),  # type: ignore[arg-type]
                    env_priv,
                    sess_matcher,  # type: ignore[arg-type]
                    _cmd_result("session", "/session clear"),
                )
        mock_perm.assert_awaited_once()
        assert any("/session clear confirm" in str(m) for m in sess_matcher.sent)

    asyncio.run(_run())
