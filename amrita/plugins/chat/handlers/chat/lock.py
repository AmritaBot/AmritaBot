"""聊天锁策略：按 chat_pending_mode 处理锁占用场景（State 模式）

从原 chat.py 的 match 分支抽出，每种模式一个策略类：
- single:            锁占用时静默跳过（stop_propagation）
- single_with_report: 锁占用时 finish 提示用户
- interactive:       锁占用时把本条消息反向推送给正在运行的 ChatObject
- 其他（默认/queue）:  不干预，排队等待
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from aiologic import Lock
from amrita_core import debug_log, logger

from ...runtime import pending_chatobj

if TYPE_CHECKING:
    from amrita_core.chatmanager import ChatObject as CoreChatObject
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher

__all__ = ["PendingModeStrategy", "get_pending_mode_strategy"]


class PendingModeStrategy(ABC):
    """锁策略基类：定义锁占用时的行为"""

    async def handle_locked(
        self,
        *,
        lock: Lock,
        matcher: Matcher,
        event: MessageEvent,
        session_id: str,
    ) -> bool:
        """处理锁占用场景。

        Returns:
            True 表示调用方应停止本次流程（return），False 表示继续。
        """
        if not lock.locked():
            return False
        return await self._on_locked(
            matcher=matcher, event=event, session_id=session_id
        )

    @abstractmethod
    async def _on_locked(
        self,
        *,
        matcher: Matcher,
        event: MessageEvent,
        session_id: str,
    ) -> bool: ...


class SkipStrategy(PendingModeStrategy):
    """single：锁占用时静默跳过"""

    async def _on_locked(
        self,
        *,
        matcher: Matcher,
        event: MessageEvent,
        session_id: str,
    ) -> bool:
        debug_log("聊天已被锁定，跳过")
        matcher.stop_propagation()
        return True


class ReportStrategy(PendingModeStrategy):
    """single_with_report：锁占用时 finish 提示用户"""

    async def _on_locked(
        self,
        *,
        matcher: Matcher,
        event: MessageEvent,
        session_id: str,
    ) -> bool:
        debug_log("聊天已被锁定，发送报告")
        await matcher.finish("聊天任务正在处理中，请稍后再试")
        return True


class InteractiveStrategy(PendingModeStrategy):
    """interactive：锁占用时通过反向流把本条消息推给正在运行的 ChatObject

    Core 在下一个 Step 边界将其消费为 [peer message] 追加到上下文。
    """

    async def _on_locked(
        self,
        *,
        matcher: Matcher,
        event: MessageEvent,
        session_id: str,
    ) -> bool:
        debug_log("聊天已被锁定，推送给正在运行的 ChatObject")
        running_chat: CoreChatObject | None = next(
            (obj for obj in pending_chatobj[session_id] if obj.is_running()),
            None,
        )
        if running_chat is not None:
            text = event.message.extract_plain_text().strip()
            try:
                await running_chat.io_stream.send_to_producer(text)
            except Exception as e:
                logger.opt(exception=e, colors=True, raw=True).warning(
                    "推送交互消息失败，已静默丢弃。"
                )
        matcher.stop_propagation()
        return True


class QueueStrategy(PendingModeStrategy):
    """queue（默认）：锁占用时不干预，排队等待"""

    async def _on_locked(
        self,
        *,
        matcher: Matcher,
        event: MessageEvent,
        session_id: str,
    ) -> bool:
        return False


def get_pending_mode_strategy(mode: str) -> PendingModeStrategy:
    """根据 chat_pending_mode 返回对应锁策略实例"""
    match mode:
        case "single":
            return SkipStrategy()
        case "single_with_report":
            return ReportStrategy()
        case "interactive":
            return InteractiveStrategy()
        case _:
            return QueueStrategy()
