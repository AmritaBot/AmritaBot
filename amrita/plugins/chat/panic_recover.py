"""Chat 工作流 Panic-Recover 事件定义。

当 ChatObject 的工作流解释器因未处理异常被 dump（panic）时，
:mod:`amrita.plugins.chat.handlers.chat` 会触发 :class:`ChatPanicRecoverEvent`。

外部模块可通过 ``amrita_core.on_event`` 注册处理器，在崩溃现场（解释器
指针、上下文、异常）做修复操作，然后调用 ``mark_continue()`` 让解释器
从 panic 状态恢复并继续执行剩余管线——这是 Sense 原生的 Panic/Recover
机制（参考 AmritaSense 的 REPL 调试器文档：崩溃后 ``_panic_exc``、
``_pointer``、``_ret_addr_stack`` 全部保留，再次驱动解释器即恢复执行）。

未注册任何处理器（或处理器未调用 ``mark_continue()``）时，行为与
旧版一致：异常路径不提交记忆（``COMMIT_MEMORY`` 节点不会执行）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from amrita_sense.hook.event import BaseEvent

if TYPE_CHECKING:
    from amrita_core import ChatObject
    from amrita_core.types import SendMessageWrap
    from amrita_sense import WorkflowInterpreter


@dataclass
class ChatPanicRecoverEvent(BaseEvent[str]):
    """解释器 panic 后触发的恢复事件。

    字段：
        chat: 触发 panic 的 ChatObject，可从其 DI 上下文读取完整运行状态。
        interpreter: 已 dump 的 WorkflowInterpreter，指针停留在崩溃节点；
            恢复执行前可调用 ``advance_pointer()`` 跳过崩溃节点，
            或修改上下文后调用 ``mark_continue()`` 重试该节点。
        exception: 导致 panic 的原始异常。
        context_wrap: 崩溃时的上下文包装（含已产生的消息增量），
            可能是 ``None``（崩溃早于 ``LOAD_STATE``）。
    """

    chat: "ChatObject"
    interpreter: "WorkflowInterpreter"
    exception: BaseException
    context_wrap: "SendMessageWrap | None"
    _continue: bool = field(default=False, init=False, repr=False)

    def get_event_type(self) -> str:
        return "CHAT_PANIC_RECOVER"

    @property
    def event_type(self) -> str:
        return "CHAT_PANIC_RECOVER"

    @property
    def should_continue(self) -> bool:
        """处理器是否已调用 :meth:`mark_continue`。"""
        return self._continue

    def mark_continue(self) -> None:
        """标记恢复：解释器将从 panic 状态继续执行。

        崩溃节点会被重新执行（相当于重试）；若希望跳过崩溃节点，
        可先调用 ``self.interpreter.advance_pointer()`` 再标记。
        """
        self._continue = True
