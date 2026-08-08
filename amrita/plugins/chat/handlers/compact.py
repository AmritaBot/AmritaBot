"""compact 指令：手动压缩当前会话上下文

复用 Core `MemoryLimiter` 执行压缩（行为与自动压缩一致）：
- 普通模式：上下文占用未达到 MaxTokens 的 15% 时拒绝压缩
- force 模式：忽略阈值，收紧长度上限强制触发摘要
"""

from __future__ import annotations

import asyncio
from copy import deepcopy

from amrita_core.chatmanager import MemoryLimiter
from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot_plugin_amrita import CachedUserDataRepository

from amrita.plugins.chat.utils.libchat import add_usage
from amrita.plugins.perm.API.rules import any_has_permission

from ..check_rule import is_bot_admin, is_group_admin_if_is_in_group
from ..config import Config, config_manager
from ..utils.context import build_train_dict, estimate_tokens
from ..utils.sql import get_uni_user_id

# 上下文占用低于 MaxTokens 该比例时拒绝压缩
COMPACT_MIN_RATIO = 0.15


async def _check_usage(
    event: MessageEvent, config: Config, dm: CachedUserDataRepository
) -> str | None:
    """检查对应维度的剩余用量是否足够（群聊只算群，私聊只算用户）

    参考 check_rule 的 usage_enough 逻辑。

    Returns:
        返回 None 表示用量足够，否则返回拒绝原因
    """
    if not config.usage_limit.enable_usage_limit:
        return None
    if await is_bot_admin(event) or await (any_has_permission("amrita.usage.bypass"))(
        event
    ):
        return None

    data = await dm.get_metadata(get_uni_user_id(event))
    if isinstance(event, GroupMessageEvent):
        limit = config.usage_limit.group_daily_limit
        token_limit = config.usage_limit.group_daily_token_limit
    else:
        limit = config.usage_limit.user_daily_limit
        token_limit = config.usage_limit.user_daily_token_limit

    if limit != -1 and data.called_count >= limit:
        return f"今日用量已达上限（{limit} 次），无法执行压缩。"
    if token_limit != -1 and (data.tokens_input + data.tokens_output >= token_limit):
        return f"今日 token 用量已达上限（{token_limit} tokens），无法执行压缩。"
    return None


async def compact(
    bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    """压缩当前会话上下文：将早期消息总结为摘要"""
    if not await is_group_admin_if_is_in_group(event, bot):
        await matcher.finish("你没有权限执行此命令。")

    arg = args.extract_plain_text().strip()
    force = arg in ("force", "-f", "--force")
    if arg and not force:
        await matcher.finish("未知参数，用法：/compact 或 /compact force")

    config = config_manager.config
    repo = CachedUserDataRepository()
    uni_id = get_uni_user_id(event)
    memory = await repo.get_memory(uni_id)
    data = memory.memory_json
    if not data.messages:
        await matcher.finish("当前会话为空，无需压缩。")

    train = build_train_dict(event, memory, config)
    max_tokens = config.core.llm.session_tokens_windows
    current_tokens = await asyncio.to_thread(estimate_tokens, train, memory, config)

    ratio = current_tokens / max_tokens if max_tokens > 0 else 1.0
    if not force and ratio < COMPACT_MIN_RATIO:
        await matcher.finish(
            f"当前上下文 {current_tokens}/{max_tokens} tokens（{ratio:.1%}），"
            f"未达到 {COMPACT_MIN_RATIO:.0%} 的压缩阈值，暂不需要压缩。"
        )

    # 检查剩余用量（压缩的摘要调用也会消耗 token）
    if (reason := await _check_usage(event, config, repo)) is not None:
        await matcher.finish(reason)

    # 执行压缩：force 时收紧长度上限确保触发摘要
    work_config = deepcopy(config.core)
    if force:
        work_config.llm.enable_memory_abstract = True
        keep = max(
            1,
            int(len(data.messages) * (1 - work_config.llm.memory_abstract_proportion)),
        )
        work_config.llm.memory_length_limit = keep

    try:
        async with repo.make_lock(uni_id):
            async with MemoryLimiter(data, train, config=work_config) as lim:
                await lim.run_enforce()
                usage = lim.usage
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception("压缩会话上下文失败。")
        await matcher.finish("压缩失败，会话已回滚。")

    after_tokens = await asyncio.to_thread(estimate_tokens, train, memory, config)
    await repo.update_memory_data(memory)

    # 摘要消耗计入用户用量统计
    if usage is not None:
        ins = await repo.get_metadata(uni_id)
        add_usage(ins, usage)
        await repo.update_metadata(ins)

    if after_tokens >= current_tokens:
        await matcher.send(
            f"当前上下文未超出限制（{current_tokens}/{max_tokens} tokens），无需压缩。"
        )
    else:
        msg = f"✅ 压缩完成：{current_tokens} → {after_tokens} tokens"
        if usage is not None:
            msg += (
                f"（摘要消耗 {usage.prompt_tokens + usage.completion_tokens} tokens）"
            )
        await matcher.send(msg)
