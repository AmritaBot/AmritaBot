"""验证 /model test 报错输出/超时/中途取消，以及空 assistant 回复不入库并提示空文本。"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nonebot
import pytest
from amrita_core import MemoryModel, PresetReport
from amrita_core.preset import TEST_MSG_PROMPT, TEST_MSG_USER
from amrita_core.types import Message, ModelPreset, TextContent, ToolCall
from nonebot.exception import FinishedException


@pytest.fixture(scope="module", autouse=True)
def _init_nb():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


class _FakeMatcher:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, msg: object) -> None:
        self.sent.append(msg)

    async def finish(self, msg: object = "") -> None:
        self.sent.append(msg)
        raise FinishedException


def _sample_preset(name: str = "demo") -> ModelPreset:
    return ModelPreset(
        name=name,
        model="gpt-demo",
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        protocol="openai",
    )


def test_model_test_reports_error_detail_and_timeout():
    """模型测试失败时输出具体报错内容，超时的预设触发独立超时报告且不拖垮其他预设。"""
    model_mod = importlib.import_module("amrita.plugins.chat.handlers.model")

    p_ok = _sample_preset("ok-model")
    p_err = _sample_preset("err-model")
    p_slow = _sample_preset("slow-model")

    async def _fake_test_single(self, preset: ModelPreset) -> PresetReport:
        if preset.name == "ok-model":
            return PresetReport(
                preset_name=preset.name,
                preset_data=preset,
                test_input=(TEST_MSG_PROMPT, TEST_MSG_USER),
                test_output=Message[list[TextContent]](
                    role="assistant",
                    content=[TextContent(type="text", text="hello")],
                ),
                token_prompt=10,
                token_completion=5,
                status=True,
                message="",
                time_used=0.12,
            )
        if preset.name == "err-model":
            return PresetReport(
                preset_name=preset.name,
                preset_data=preset,
                test_input=(TEST_MSG_PROMPT, TEST_MSG_USER),
                test_output=None,
                token_prompt=-1,
                token_completion=0,
                status=False,
                message="[openai] Error code: 401 - invalid api key",
                time_used=0.0,
            )
        await asyncio.sleep(5)
        raise AssertionError("should have timed out")

    matcher = _FakeMatcher()
    fake_event = SimpleNamespace(self_id=10000)

    async def _run() -> None:
        with (
            patch.object(
                model_mod.config_manager,
                "get_all_presets",
                AsyncMock(return_value=[p_ok, p_err, p_slow]),
            ),
            patch.object(
                model_mod.MultiPresetManager,
                "test_single_preset",
                _fake_test_single,
            ),
        ):
            await model_mod.model_test(
                fake_event,  # type: ignore[arg-type]
                matcher,  # type: ignore[arg-type]
                SimpleNamespace(),  # type: ignore[arg-type]
                "",
                detailed=False,
                timeout=0.15,
            )

    asyncio.run(_run())
    assert len(matcher.sent) == 2
    report_text = str(matcher.sent[-1])
    assert "成功1个，失败2个" in report_text
    assert "✅ ok-model" in report_text
    assert "❌ err-model" in report_text
    assert "401 - invalid api key" in report_text
    assert "❌ slow-model" in report_text
    assert "请求超时" in report_text


def test_model_test_can_be_cancelled_midway():
    """模型测试运行期间收到 /model test cancel 能立即中止并释放 TEST_LOCK。"""
    model_mod = importlib.import_module("amrita.plugins.chat.handlers.model")

    preset = _sample_preset("hang-model")
    started = asyncio.Event()

    async def _fake_hang(self, p: ModelPreset) -> PresetReport:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("should be cancelled")

    run_matcher = _FakeMatcher()
    cancel_matcher = _FakeMatcher()
    fake_event = SimpleNamespace(self_id=10000)

    async def _run() -> None:
        with (
            patch.object(
                model_mod.config_manager,
                "get_preset",
                AsyncMock(return_value=preset),
            ),
            patch.object(
                model_mod.MultiPresetManager,
                "test_single_preset",
                _fake_hang,
            ),
        ):
            t = asyncio.create_task(
                model_mod.model_test(
                    fake_event,  # type: ignore[arg-type]
                    run_matcher,  # type: ignore[arg-type]
                    SimpleNamespace(),  # type: ignore[arg-type]
                    "hang-model",
                    detailed=False,
                    timeout=10.0,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=2.0)
            with pytest.raises(FinishedException):
                await model_mod.model_test_cancel(cancel_matcher)  # type: ignore[arg-type]
            await asyncio.wait_for(t, timeout=2.0)

    asyncio.run(_run())
    assert not model_mod.TEST_LOCK.locked()
    assert any("已发送取消信号" in str(m) for m in cancel_matcher.sent)
    assert any("已取消" in str(m) for m in run_matcher.sent)


def test_parse_test_args():
    from amrita.plugins.chat.handlers.model import _parse_test_args

    assert _parse_test_args(["cancel"]) == (True, "", False, None, None)
    assert _parse_test_args(["取消"]) == (True, "", False, None, None)
    assert _parse_test_args(["11FD", "-d", "-t", "15"]) == (
        False,
        "11FD",
        True,
        15.0,
        None,
    )
    assert _parse_test_args(["--timeout=20", "11FD"]) == (
        False,
        "11FD",
        False,
        20.0,
        None,
    )
    is_cancel, _, _, _, err = _parse_test_args(["-t", "-5"])
    assert is_cancel is False
    assert err is not None


def test_empty_assistant_message_not_committed_and_warns_user():
    """空 content 且无 tool_calls 的 assistant 消息不会写入 memory，且 send_final 输出空文本提示。"""
    from amrita.plugins.chat.backends import ChatMemoryBackend
    from amrita.plugins.chat.utils.stream_sender import ChatStreamSender

    # 1. 验证 ChatMemoryBackend.commit_memory 剔除空 assistant，但保留带 tool_calls 与非空消息
    mem_val = SimpleNamespace(memory_json=MemoryModel(messages=[]))
    mem_view = MemoryModel(messages=[])
    backend = ChatMemoryBackend(mem_val, mem_view)  # type: ignore[arg-type]
    backend.repo = SimpleNamespace(update_memory_data=AsyncMock())  # type: ignore[assignment]

    tool_call_msg = Message(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                function={"name": "ping", "arguments": "{}"},
            )
        ],
    )
    runtime_mem = MemoryModel(
        messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content=""),
            Message(role="assistant", content="   \n"),
            tool_call_msg,
            Message(role="assistant", content="real reply"),
        ]
    )

    asyncio.run(backend.commit_memory("sess-1", runtime_mem))
    saved_msgs = mem_val.memory_json.messages
    assert len(saved_msgs) == 3
    assert saved_msgs[0].role == "user"
    assert saved_msgs[1].tool_calls is not None
    assert saved_msgs[2].content == "real reply"

    # 2. 验证 ChatStreamSender.send_final 遇空响应输出 "❌ 模型提供商返回空文本"
    matcher = _FakeMatcher()
    fake_chat = SimpleNamespace(_di_resp=SimpleNamespace(response=None, usage=None))
    fake_event = SimpleNamespace(message_id=1, self_id=10000)
    fake_cfg = SimpleNamespace(
        meta=SimpleNamespace(reasoning_summary=False),
        function=SimpleNamespace(
            forward_threshold=200,
            forward_min_chunk=50,
            nature_chat_style=False,
        ),
    )
    sender = ChatStreamSender(
        matcher,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        fake_event,  # type: ignore[arg-type]
        fake_cfg,  # type: ignore[arg-type]
        fake_chat,  # type: ignore[arg-type]
    )

    asyncio.run(sender.send_final("   "))
    assert matcher.sent == ["❌ 模型提供商返回空文本"]
