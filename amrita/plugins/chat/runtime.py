"""
Runtime 基础设施

提供 Bot 级别的 ChatManager 实例和跨 handler 共享的类型定义。
会话管理逻辑已移至 runtime_session.py。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TypedDict

from amrita_core.chatmanager import ChatManager
from nonebot.adapters.onebot.v11 import Bot
from nonebot.adapters.onebot.v11.event import MessageEvent
from nonebot.matcher import Matcher

from amrita.plugins.chat.config import Config
from amrita.plugins.chat.utils.app import (
    AwaredMemory,
    MemorySchema,
)


class AmritaBotContext(TypedDict):
    """
    通过 ChatObject._hook_kwargs["amrita"] 传递的上下文。

    handler 在创建 ChatObject 时填充此字典，
    chatobj.py 等管理模块通过 _hook_kwargs 读取。
    """

    matcher: Matcher
    data: AwaredMemory
    memory: MemorySchema
    bot: Bot
    event: MessageEvent
    bot_config: Config


bot_chat_manager = ChatManager()

# 使用隐式锁队列追踪 pending 状态
# key = session_id (get_uni_user_id), value = 正在等待锁的 asyncio.Task 列表
pending_tasks: defaultdict[str, list[asyncio.Task]] = defaultdict(list)
