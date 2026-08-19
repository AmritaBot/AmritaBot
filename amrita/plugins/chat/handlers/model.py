"""/model 域命令：模型查看、切换与测试（合并原 presets/set_preset/test_preset）"""

from __future__ import annotations

import asyncio
import json

from aiologic import Lock
from amrita_core import PresetReport
from amrita_core.preset import MultiPresetManager
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.utils.send import send_forward_msg

from ..config import config_manager

TEST_LOCK = Lock()


def _format_preset_line(preset) -> str:
    """格式化单个预设行（标记当前使用的）"""
    marker = "⭐ " if preset.name == config_manager.config.preset else "   "
    return f"{marker}{preset.name}（{preset.model}）"


async def model_list(matcher: Matcher) -> None:
    """列出所有可用模型"""
    msg = f"当前模型：{config_manager.config.preset}\n\n可用模型：\n"
    for preset in await config_manager.get_all_presets():
        msg += _format_preset_line(preset) + "\n"
    await matcher.finish(msg)


async def model_switch(
    event: MessageEvent, matcher: Matcher, bot: Bot, name: str
) -> None:
    """切换当前模型预设"""
    if not name:
        await matcher.finish("请指定要切换的模型名，如：/model switch claude-thinking")
    for model in await config_manager.get_all_presets():
        if model.name == name:
            config_manager.ins_config.preset = model.name
            await config_manager.save_config()
            await matcher.finish(f"✅ 已切换到：{model.name}（{model.model}）")
    await matcher.finish(f"未找到模型 {name}，请输入 /model list 查看可用模型。")


async def model_info(event: MessageEvent, matcher: Matcher, bot: Bot) -> None:
    """展示当前模型的详细信息（模型名、思考深度）"""
    preset = await config_manager.get_preset(config_manager.config.preset)
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


async def model_test(
    event: MessageEvent, matcher: Matcher, bot: Bot, name: str, detailed: bool
) -> None:
    """测试指定模型（不指定则测试全部）"""
    pm = MultiPresetManager()
    if name:
        try:
            presets = [await config_manager.get_preset(name)]
        except Exception:
            await matcher.finish(
                f"未找到模型 {name}，请输入 /model list 查看可用模型。"
            )
    else:
        presets = await config_manager.get_all_presets(True)
    if TEST_LOCK.locked():
        await matcher.finish("当前仍然有1个测试任务正在执行，请稍后再试。")
    async with TEST_LOCK:
        await matcher.send(f"开始测试（共计{len(presets)}个）...")
        results: list[PresetReport] = await asyncio.gather(
            *[pm.test_single_preset(preset) for preset in presets]
        )
    ok = len([r for r in results if r.status])
    if detailed:
        # summary 只出现一次，各预设仅展示自身细节
        summary = (
            f"测试结果：\n"
            f"测试完成，共测试{len(results)}个预设，成功{ok}个，失败{len(results) - ok}个。\n"
        )
        detail_msgs = [
            MessageSegment.text(
                f"预设：{result.preset_name}\n"
                f"测试输入：{json.dumps(result.test_input[0].model_dump(), ensure_ascii=False)} | {json.dumps(result.test_input[1].model_dump(), ensure_ascii=False)}\n"
                f"测试输出：{json.dumps(result.test_output.model_dump(), ensure_ascii=False) if result.test_output else None}\n"
                f"输入token消耗：{result.token_prompt}\n"
                f"输出token消耗：{result.token_completion}\n"
                f"时间消耗：{result.time_used:.4f}s\n"
                f"测试成功：{result.status}\n"
            )
            for result in results
        ]
        await send_forward_msg(
            bot,
            event,
            "Amrita-测试结果",
            str(event.self_id),
            [MessageSegment.text(summary), *detail_msgs],
        )
    else:
        msg = (
            f"测试完成，共测试{len(results)}个预设，成功{ok}个，失败{len(results) - ok}个。\n"
            + "".join(
                [
                    (
                        f"预设：{result.preset_name}"
                        f"  时间消耗：{result.time_used:.4f}s"
                        f"  测试成功：{result.status}"
                    )
                    for result in results
                ]
            )
        )
        await matcher.send(msg)


async def model(
    event: MessageEvent, matcher: Matcher, bot: Bot, args: Message = CommandArg()
):
    """/model 命令入口：list / switch <名> / info / test [名] [-d]"""
    arg_list = args.extract_plain_text().strip().split()
    sub = arg_list[0] if arg_list else "list"
    rest = arg_list[1:]

    match sub:
        case "list" | "ls" | "查看":
            await model_list(matcher)
        case "switch" | "use" | "set" | "切换":
            await model_switch(event, matcher, bot, rest[0] if rest else "")
        case "info" | "详情" | "当前":
            await model_info(event, matcher, bot)
        case "test" | "测试" | "check":
            name = (
                rest[0]
                if rest and rest[0] not in ("-d", "--detail", "--details")
                else ""
            )
            detailed = any(a in ("-d", "--detail", "--details") for a in rest)
            await model_test(event, matcher, bot, name, detailed)
        case _:
            await matcher.finish(
                "用法：\n"
                "/model list — 查看可用模型\n"
                "/model switch <名> — 切换模型\n"
                "/model info — 当前模型详情\n"
                "/model test [名] [-d] — 测试模型"
            )
