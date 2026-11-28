"""/model 域命令：模型查看、切换与测试（合并原 presets/set_preset/test_preset）"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from aiologic import Lock
from amrita_core import PresetReport
from amrita_core.preset import TEST_MSG_PROMPT, TEST_MSG_USER, MultiPresetManager
from amrita_core.types import ModelPreset
from nonebot.adapters import Bot
from nonebot.matcher import Matcher
from nonebot_plugin_alconna import AlconnaResult, CommandResult

from amrita.platform.di import EnvelopeNBDep
from amrita.platform.dto import Envelope
from amrita.utils.send import send_forward_msg

from ..config import config_manager
from ._alconna import extract_raw_args

TEST_LOCK = Lock()
DEFAULT_TEST_TIMEOUT_SECONDS = 30.0

_active_test_task: asyncio.Task[list[PresetReport]] | None = None
_active_test_cancel_event: asyncio.Event | None = None


def _resolve_test_timeout() -> float:
    """获取模型测试的单预设超时秒数（复用配置 llm_timeout，保底 30s 上限）。"""
    configured = float(getattr(config_manager.config.core.llm, "llm_timeout", 0) or 0)
    if configured > 0:
        return min(configured, 60.0)
    return DEFAULT_TEST_TIMEOUT_SECONDS


def _extract_error_detail(report: PresetReport) -> str:
    """提炼测试失败时的报错详情，避免空串或过长刷屏。"""
    msg = (report.message or "").strip()
    if not msg:
        return "未知错误（未返回异常信息）"
    if len(msg) > 500:
        return msg[:500] + "…"
    return msg


def _format_preset_line(preset) -> str:
    """格式化单个预设行（标记当前使用的）"""
    marker = "⭐ " if preset.name == config_manager.config.preset else "   "
    return f"{marker}{preset.name}（{preset.model}）"


async def _test_preset_with_timeout(
    pm: MultiPresetManager, preset: ModelPreset, timeout: float
) -> PresetReport:
    """带独立超时控制的单预设测试；超时或意外异常统一返回含错误详情的 PresetReport。"""
    started = time.monotonic()
    try:
        report = await asyncio.wait_for(
            pm.test_single_preset(preset),
            timeout=timeout,
        )
        # 补齐失败耗时（amrita_core 异常分支 time_used 固定为 0）
        if not report.status and report.time_used <= 0:
            report.time_used = time.monotonic() - started
        return report
    except asyncio.TimeoutError:
        return PresetReport(
            preset_name=preset.name,
            preset_data=preset,
            test_input=(TEST_MSG_PROMPT, TEST_MSG_USER),
            test_output=None,
            token_prompt=-1,
            token_completion=0,
            status=False,
            message=f"请求超时（超过 {timeout:g}s）",
            time_used=time.monotonic() - started,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return PresetReport(
            preset_name=preset.name,
            preset_data=preset,
            test_input=(TEST_MSG_PROMPT, TEST_MSG_USER),
            test_output=None,
            token_prompt=-1,
            token_completion=0,
            status=False,
            message=f"{type(exc).__name__}: {exc}",
            time_used=time.monotonic() - started,
        )


def _format_brief_result(result: PresetReport) -> str:
    """格式化单条简要测试结果；失败时附带具体报错。"""
    if result.status:
        return f"✅ {result.preset_name}  耗时：{result.time_used:.2f}s"
    return (
        f"❌ {result.preset_name}  耗时：{result.time_used:.2f}s\n"
        f"   错误：{_extract_error_detail(result)}"
    )


def _format_detail_result(result: PresetReport) -> str:
    """格式化单条详细测试结果。"""
    lines = [
        f"预设：{result.preset_name}",
        f"状态：{'成功' if result.status else '失败'}",
        f"时间消耗：{result.time_used:.4f}s",
    ]
    if not result.status:
        lines.append(f"错误信息：{_extract_error_detail(result)}")
    lines.extend(
        [
            f"测试输入：{json.dumps(result.test_input[0].model_dump(), ensure_ascii=False)} | "
            f"{json.dumps(result.test_input[1].model_dump(), ensure_ascii=False)}",
            f"测试输出：{json.dumps(result.test_output.model_dump(), ensure_ascii=False) if result.test_output else None}",
            f"输入token消耗：{result.token_prompt}",
            f"输出token消耗：{result.token_completion}",
        ]
    )
    return "\n".join(lines) + "\n"


async def model_list(matcher: Matcher) -> None:
    """列出所有可用模型"""
    msg = f"当前模型：{config_manager.config.preset}\n\n可用模型：\n"
    for preset in await config_manager.get_all_presets():
        msg += _format_preset_line(preset) + "\n"
    await matcher.finish(msg)


async def model_switch(matcher: Matcher, name: str) -> None:
    """切换当前模型预设"""
    if not name:
        await matcher.finish("请指定要切换的模型名，如：/model switch claude-thinking")
    for model in await config_manager.get_all_presets():
        if model.name == name:
            config_manager.ins_config.preset = model.name
            await config_manager.save_config()
            await matcher.finish(f"✅ 已切换到：{model.name}（{model.model}）")
    await matcher.finish(f"未找到模型 {name}，请输入 /model list 查看可用模型。")


async def model_info(matcher: Matcher) -> None:
    """展示当前模型的详细信息（模型名、思考深度）"""
    preset = await config_manager.get_preset(
        config_manager.config.preset, fix=True, cache=True
    )
    assert preset is not None  # fix 回退保证存在（目录为空时默认创建 default）
    msg = (
        f"当前模型：{preset.name}（{preset.model}）\n"
        f"接口：{preset.base_url or '默认'}\n"
        f"协议：{preset.protocol}\n"
    )
    if preset.thinking_config is not None:
        tc = preset.thinking_config
        enabled = tc.thinking_type == "enabled" or tc.enable_thinking is True
        msg += f"思考：{'已启用' if enabled else '已关闭'}（深度 {tc.thinking_effort or '—'}）\n"
    await matcher.finish(msg)


async def model_test_cancel(matcher: Matcher) -> None:
    """取消当前正在执行的模型测试任务。"""
    global _active_test_task, _active_test_cancel_event
    task = _active_test_task
    if task is None or task.done():
        await matcher.finish("当前没有正在进行的模型测试任务。")
    if _active_test_cancel_event is not None:
        _active_test_cancel_event.set()
    task.cancel()
    await matcher.finish("🛑 已发送取消信号，正在中止当前模型测试任务。")


async def model_test(
    env: Envelope,
    matcher: Matcher,
    bot: Bot,
    name: str,
    detailed: bool,
    timeout: float | None = None,
) -> None:
    """测试指定模型（不指定则测试全部），支持单预设超时与中途取消。"""
    global _active_test_task, _active_test_cancel_event
    pm = MultiPresetManager()
    if name:
        preset = await config_manager.get_preset(name, fix=False, cache=True)
        if preset is None:
            await matcher.finish(
                f"未找到模型 {name}，请输入 /model list 查看可用模型。"
            )
        presets = [preset]
    else:
        presets = await config_manager.get_all_presets(True)

    if TEST_LOCK.locked():
        await matcher.finish(
            "当前仍然有1个测试任务正在执行，可发送 /model test cancel 中止，或稍后再试。"
        )

    effective_timeout = (
        timeout if timeout is not None and timeout > 0 else _resolve_test_timeout()
    )

    async with TEST_LOCK:
        await matcher.send(
            f"开始测试（共计{len(presets)}个，单模型超时 {effective_timeout:g}s，发送 /model test cancel 可中途取消）..."
        )
        cancel_event = asyncio.Event()
        _active_test_cancel_event = cancel_event

        async def _run_all() -> list[PresetReport]:
            subtasks = [
                asyncio.create_task(
                    _test_preset_with_timeout(pm, preset, effective_timeout)
                )
                for preset in presets
            ]
            try:
                return list(await asyncio.gather(*subtasks))
            except asyncio.CancelledError:
                for sub in subtasks:
                    if not sub.done():
                        sub.cancel()
                with contextlib.suppress(BaseException):
                    await asyncio.gather(*subtasks, return_exceptions=True)
                raise

        task = asyncio.create_task(_run_all())
        _active_test_task = task
        try:
            results = await task
        except asyncio.CancelledError:
            if cancel_event.is_set():
                await matcher.send("⚠️ 模型测试已取消。")
                return
            raise
        finally:
            if _active_test_task is task:
                _active_test_task = None
            if _active_test_cancel_event is cancel_event:
                _active_test_cancel_event = None

    ok = len([r for r in results if r.status])
    failed = len(results) - ok
    if detailed:
        summary = (
            f"测试结果：\n"
            f"测试完成，共测试{len(results)}个预设，成功{ok}个，失败{failed}个。\n"
        )
        detail_msgs = [_format_detail_result(result) for result in results]
        await send_forward_msg(
            bot,
            env,
            "Amrita-测试结果",
            env.self_id or str(bot.self_id),
            [summary, *detail_msgs],
        )
    else:
        lines = [
            f"测试完成，共测试{len(results)}个预设，成功{ok}个，失败{failed}个。",
            *(_format_brief_result(result) for result in results),
        ]
        await matcher.send("\n".join(lines))


def _parse_test_args(
    rest: list[str],
) -> tuple[bool, str, bool, float | None, str | None]:
    """解析 /model test 参数，返回 (is_cancel, name, detailed, timeout, err_msg)。"""
    if rest and rest[0].lower() in ("cancel", "stop", "abort", "取消"):
        return True, "", False, None, None

    name = ""
    detailed = False
    timeout: float | None = None
    idx = 0
    while idx < len(rest):
        tok = rest[idx]
        if tok in ("-d", "--detail", "--details"):
            detailed = True
        elif tok in ("-t", "--timeout"):
            if idx + 1 >= len(rest):
                return False, "", False, None, "❌ 请在 -t/--timeout 后提供超时秒数。"
            idx += 1
            try:
                timeout = float(rest[idx])
            except ValueError:
                return False, "", False, None, f"❌ 超时时间必须是正数：{rest[idx]}"
            if timeout <= 0:
                return False, "", False, None, "❌ 超时时间必须大于 0 秒。"
        elif tok.startswith("--timeout="):
            raw = tok.split("=", 1)[1]
            try:
                timeout = float(raw)
            except ValueError:
                return False, "", False, None, f"❌ 超时时间必须是正数：{raw}"
            if timeout <= 0:
                return False, "", False, None, "❌ 超时时间必须大于 0 秒。"
        elif not name:
            name = tok
        idx += 1
    return False, name, detailed, timeout, None


async def model(
    bot: Bot,
    env: EnvelopeNBDep,
    matcher: Matcher,
    result: CommandResult = AlconnaResult(),
):
    """/model 命令入口：list / switch <名> / info / test [名] [-d] [-t 秒] / test cancel"""
    arg_list = extract_raw_args(result).strip().split()
    sub = arg_list[0] if arg_list else "list"
    rest = arg_list[1:]

    match sub:
        case "list" | "ls" | "查看":
            await model_list(matcher)
        case "switch" | "use" | "set" | "切换":
            await model_switch(matcher, rest[0] if rest else "")
        case "info" | "详情" | "当前":
            await model_info(matcher)
        case "test" | "测试" | "check":
            is_cancel, name, detailed, timeout, err_msg = _parse_test_args(rest)
            if err_msg:
                await matcher.finish(err_msg)
            if is_cancel:
                await model_test_cancel(matcher)
            await model_test(env, matcher, bot, name, detailed, timeout=timeout)
        case "cancel" | "stop" | "abort" | "取消":
            await model_test_cancel(matcher)
        case _:
            await matcher.finish(
                "用法：\n"
                "/model list — 查看可用模型\n"
                "/model switch <名> — 切换模型\n"
                "/model info — 当前模型详情\n"
                "/model test [名] [-d] [-t 秒] — 测试模型\n"
                "/model test cancel — 取消正在进行的测试"
            )
