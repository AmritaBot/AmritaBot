"""会话运行态守卫

破坏性 ``/session`` 子命令与正在运行的对话共享同一份 ``memory_json``：
本轮结束时 ``ChatMemoryBackend.commit_memory`` 会把运行中的消息写回，
覆盖掉指令刚做的修改（归档被复活、恢复被覆盖、清空被回填）。

因此破坏性指令**必须**始终持有 ``session_lock``，不能只在检测到忙碌时才持锁：
``is_session_busy`` 与真正的执行之间存在窗口，空闲检查通过后仍可能插入新一轮对话。
``is_session_busy`` 只用于决定是否直接拒绝（未显式 ``force`` 时给出提示），
真正的互斥由 ``session_lock`` 保证。
"""

from __future__ import annotations

import aiologic
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from .lock import get_group_lock, get_private_lock

__all__ = ["is_session_busy", "session_lock"]


def is_session_busy(session_id: str) -> bool:
    """会话当前是否有未完成的对话在运行。

    Args:
        session_id: 统一会话 ID（``get_uni_user_id``）

    Returns:
        有运行中的 ``ChatObject`` 时为 ``True``
    """
    #  延迟导入：runtime 会拉起配置模块，避免与 handler 形成循环依赖
    from ..runtime import bot_chat_manager, pending_chatobj

    if any(not obj.is_done() for obj in bot_chat_manager.get_objs(session_id)):
        return True
    return any(obj.is_running() for obj in pending_chatobj.get(session_id, ()))


def session_lock(event: MessageEvent) -> aiologic.Lock:
    """取得该会话在 chat 主路径上使用的同一把锁。

    必须复用 ``get_group_lock`` / ``get_private_lock``：``repo.make_lock``
    是数据库侧的独立锁池，chat 路径并不持有，抢它无法等到本轮结束。

    Args:
        event: 消息事件

    Returns:
        该会话的 ``aiologic.Lock``
    """
    if isinstance(event, GroupMessageEvent):
        return get_group_lock(event.group_id)
    return get_private_lock(event.user_id)
