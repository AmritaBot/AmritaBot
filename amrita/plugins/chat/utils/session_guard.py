"""会话运行态守卫

破坏性 ``/session`` 子命令与正在运行的对话共享同一份 ``memory_json``：
本轮结束时 ``ChatMemoryBackend.commit_memory`` 会把运行中的消息写回，
覆盖掉指令刚做的修改（归档被复活、恢复被覆盖、清空被回填）。

因此破坏性指令**必须**始终持有 ``session_lock``，不能只在检测到忙碌时才持锁：
``is_session_busy`` 与真正的执行之间存在窗口，空闲检查通过后仍可能插入新一轮对话。
``is_session_busy`` 只用于决定是否直接拒绝（未显式 ``force`` 时给出提示），
真正的互斥由 ``session_lock`` 保证。

本模块同时提供 ``active_chat_object``：运行中的会话必须从活对象读状态，
``repo`` 缓存的 ``memory_json`` 要等 ``COMMIT_MEMORY`` 才更新。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiologic
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from .lock import get_group_lock, get_private_lock

if TYPE_CHECKING:
    from amrita_core.chatmanager import ChatObject as CoreChatObject

__all__ = ["active_chat_object", "is_session_busy", "session_lock"]


def active_chat_object(session_id: str) -> CoreChatObject | None:
    """取得该会话最近一次运行的 ``ChatObject``。

    ``ChatObject`` 开始运行时由 Core 绑定到 ``bot_chat_manager``
    （``_entry`` 里 ``add_chat_object``，按最近优先插入），所以直接取最新
    的一个即可。排队等锁的对象不在 manager 里，但它还没跑 ``LOAD_STATE``，
    没有可读的活状态，无需关心。

    Args:
        session_id: 统一会话 ID（``get_uni_user_id``）

    Returns:
        最近一次运行且尚未结束的对象；会话空闲时为 ``None``
    """
    #  延迟导入：runtime 会拉起配置模块，避免与 handler 形成循环依赖
    from ..runtime import bot_chat_manager

    running = [
        obj for obj in bot_chat_manager.get_objs(session_id) if not obj.is_done()
    ]
    if not running:
        return None
    return max(running, key=lambda obj: obj.last_call)


def is_session_busy(session_id: str) -> bool:
    """会话当前是否有本轮在跑，或已有消息在排队等锁。

    Args:
        session_id: 统一会话 ID（``get_uni_user_id``）

    Returns:
        有运行中或排队中的 ``ChatObject`` 时为 ``True``
    """
    from ..runtime import pending_chatobj

    if active_chat_object(session_id) is not None:
        return True
    #  排队中的对象尚未开始运行（is_running() 为 False），须按「未运行且未结束」判定
    return any(
        not obj.is_running() and not obj.is_done()
        for obj in pending_chatobj.get(session_id, ())
    )


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
