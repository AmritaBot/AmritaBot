"""Panic-Recover 处理（从原 chat.py 抽出）

解释器 panic 后触发 ChatPanicRecoverEvent 让外部处理器决定是否恢复；
恢复成功则继续执行剩余管线（含 COMMIT_MEMORY 记忆提交），否则返回
NOT_RECOVERED 由调用方走旧路径（提示用户、不提交记忆）。
"""

from __future__ import annotations

from asyncio import CancelledError
from enum import Enum
from typing import TYPE_CHECKING

from amrita_core import logger
from amrita_sense.hook.matcher import MatcherFactory
from nonebot.exception import MatcherException, ProcessException

from ...panic_recover import ChatPanicRecoverEvent

if TYPE_CHECKING:
    from amrita_core.chatmanager import ChatObject as CoreChatObject

    from ...config import Config

__all__ = ["RecoveryResult", "try_panic_recover"]


class RecoveryResult(Enum):
    """Panic-Recover 结果"""

    RECOVERED = "recovered"  # 恢复成功，调用方应继续正常收尾（send_final）
    ABANDONED = "abandoned"  # 恢复尝试再次异常，已放弃本次任务
    NOT_RECOVERED = "not_recovered"  # 事件处理方未要求继续，走旧路径


async def try_panic_recover(
    chat: CoreChatObject,
    exception: BaseException,
    config: Config,
) -> RecoveryResult:
    """触发 Panic-Recover 事件并驱动解释器从崩溃节点继续。

    Args:
        chat: 发生异常的 ChatObject（panic 现场保留在 interpreter 上）
        exception: 原始异常
        config: 配置

    Returns:
        恢复结果（RECOVERED / ABANDONED / NOT_RECOVERED）
    """
    panic_event = ChatPanicRecoverEvent(
        chat=chat,
        interpreter=chat._interpreter,
        exception=exception,
        context_wrap=chat._di_working.context_wrap,
    )
    await MatcherFactory.trigger_event(
        panic_event,
        config,
        chat,
        slot=chat.slot,
        exception_ignored=(ProcessException, MatcherException),
    )
    if not panic_event.should_continue:
        return RecoveryResult.NOT_RECOVERED

    try:
        # Sense 原生 panic-recover：再次驱动解释器，从崩溃节点继续
        await chat._interpreter.run()
    except BaseException as e2:
        if not isinstance(e2, CancelledError):
            logger.opt(exception=e2, colors=True, raw=True).exception(
                "Panic-Recover 后解释器再次异常，已放弃本次任务"
            )
        return RecoveryResult.ABANDONED

    return RecoveryResult.RECOVERED
