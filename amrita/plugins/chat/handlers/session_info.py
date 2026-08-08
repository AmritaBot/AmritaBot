"""session info 指令：展示当前会话元信息

展示内容（对应 /session info）：
- 当前模型（预设名 + 模型名）
- 思考深度（preset.thinking_config 存在时显示）
- 上下文 tokens / MaxTokens（现场计算，口径对齐 MemoryLimiter）
- 消息数与角色分布
"""

from __future__ import annotations

import asyncio
from collections import Counter

from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.matcher import Matcher
from nonebot_plugin_amrita import CachedUserDataRepository

from ..check_rule import is_group_admin_if_is_in_group
from ..config import config_manager
from ..utils.context import build_train_dict, estimate_tokens
from ..utils.sql import get_uni_user_id


async def session_info(bot: Bot, event: MessageEvent, matcher: Matcher):
    """展示当前会话的模型、思考深度与上下文 token 占用"""
    if not await is_group_admin_if_is_in_group(event, bot):
        await matcher.finish("你没有权限执行此命令。")

    config = config_manager.config
    repo = CachedUserDataRepository()
    memory = await repo.get_memory(get_uni_user_id(event))
    data = memory.memory_json

    preset = await config_manager.get_preset(config.preset)
    train = build_train_dict(event, memory, config)
    max_tokens = config.core.llm.session_tokens_windows
    total = await asyncio.to_thread(estimate_tokens, train, memory, config)

    roles = Counter(getattr(msg, "role", "?") for msg in data.messages)

    lines = ["📊 当前会话元信息"]
    lines.append(f"模型：{preset.name}（{preset.model}）")
    if preset.thinking_config is not None:
        tc = preset.thinking_config
        enabled = tc.thinking_type == "enabled" or tc.enable_thinking is True
        state = "已启用" if enabled else "已关闭"
        lines.append(f"思考深度：{tc.thinking_effort or '—'}（{state}）")
    lines.append(
        f"上下文：{total} / {max_tokens} tokens"
        + (f"（{total / max_tokens:.1%}）" if max_tokens > 0 else "")
    )
    detail = " ".join(f"{role}:{count}" for role, count in roles.items())
    lines.append(f"消息数：{len(data.messages)} 条（{detail or '空'}）")
    await matcher.send("\n".join(lines))
