"""/chat 域命令：聊天开关管理（合并原 enable/disable/autochat）"""

from __future__ import annotations

from nonebot import logger
from nonebot.matcher import Matcher
from nonebot_plugin_alconna import AlconnaResult, CommandResult

from amrita.platform.di import EnvelopeNBDep
from amrita.platform.dto import Envelope

from ..utils.app import CachedGroupDataRepository
from ._alconna import extract_raw_args


async def _set_chat(env: Envelope, matcher: Matcher, on: bool) -> None:
    """开启/关闭群聊"""
    repo = CachedGroupDataRepository()
    group_config = await repo.get_group_config(env.scope)
    group_config.enable = on
    await repo.update_group_config(group_config)
    logger.debug(f"{env.scope.id} {'enabled' if on else 'disabled'}")
    await matcher.send("✅ 已启用聊天功能" if on else "已禁用聊天功能")


async def _set_auto(env: Envelope, matcher: Matcher, on: bool) -> None:
    """开启/关闭自动回复（FakePeople）"""
    repo = CachedGroupDataRepository()
    group_config = await repo.get_group_config(env.scope)
    group_config.autoreply = on
    await repo.update_group_config(group_config)
    await matcher.send("✅ 已开启自动回复" if on else "已关闭自动回复")


async def _chat_status(env: Envelope, matcher: Matcher) -> None:
    """展示当前群聊所有开关状态"""
    repo = CachedGroupDataRepository()
    group_config = await repo.get_group_config(env.scope)
    await matcher.send(
        f"📋 当前群聊状态：\n"
        f"聊天功能：{'✅ 开启' if group_config.enable else '❌ 关闭'}\n"
        f"自动回复：{'✅ 开启' if group_config.autoreply else '❌ 关闭'}"
    )


async def chat(
    env: EnvelopeNBDep,
    matcher: Matcher,
    result: CommandResult = AlconnaResult(),
):
    """/chat 命令入口：on/off/auto <on|off>/status"""
    if not env.is_group:
        await matcher.finish("该命令仅支持在群聊中使用。")

    arg_list = extract_raw_args(result).strip().split()
    if not arg_list:
        await _chat_status(env, matcher)
        return

    match arg_list[0]:
        case "on" | "开" | "启用" | "enable":
            await _set_chat(env, matcher, True)
        case "off" | "关" | "禁用" | "disable":
            await _set_chat(env, matcher, False)
        case "auto" | "自动回复" | "autoreply" | "fakepeople":
            if len(arg_list) < 2:
                await matcher.finish("用法：/chat auto <on|off>")
            if arg_list[1] in ("on", "开", "启用", "enable"):
                await _set_auto(env, matcher, True)
            elif arg_list[1] in ("off", "关", "禁用", "disable"):
                await _set_auto(env, matcher, False)
            else:
                await matcher.finish("参数必须是 on 或 off。")
        case "status" | "状态" | "查看":
            await _chat_status(env, matcher)
        case _:
            await matcher.finish(
                "用法：\n"
                "/chat — 查看状态\n"
                "/chat on|off — 开启/关闭聊天\n"
                "/chat auto <on|off> — 自动回复开关\n"
                "/chat status — 查看状态"
            )
