"""插件安装 / 卸载任务的状态与进度登记。

安装要走网络、可能耗时几十秒，接口不能同步等；因此每次操作起一个后台任务，
立刻把 ``task_id`` 返回给前端，再由 WebSocket 的 ``plugins`` 频道推流，
或由前端轮询 ``GET /api/bot/plugins/tasks/{task_id}`` 兜底。
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

__all__ = [
    "PluginTask",
    "TaskAction",
    "TaskManager",
    "TaskState",
    "get_task_manager",
]

#: 单个任务保留的输出行数上限
_MAX_LINES = 500

#: 保留的已完成任务数量
_KEEP_FINISHED = 50

TaskAction = Literal["install", "uninstall"]
TaskListener = Callable[["PluginTask"], Awaitable[None]]


class TaskState(str, Enum):
    """任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class PluginTask:
    """一次安装或卸载的完整记录。"""

    id: str
    action: TaskAction
    package: str
    module_name: str
    target: str = "amrita"
    state: TaskState = TaskState.PENDING
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=_MAX_LINES))
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def finished(self) -> bool:
        """任务是否已经结束。"""
        return self.state in (TaskState.SUCCEEDED, TaskState.FAILED)

    def to_dict(self, *, with_lines: bool = True) -> dict[str, Any]:
        """转成可直接 JSON 序列化的字典。"""
        data: dict[str, Any] = {
            "id": self.id,
            "action": self.action,
            "package": self.package,
            "module_name": self.module_name,
            "target": self.target,
            "state": self.state.value,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }
        if with_lines:
            data["lines"] = list(self.lines)
        return data


class TaskManager:
    """进程内任务登记表，带变更通知。"""

    def __init__(self, *, keep: int = _KEEP_FINISHED) -> None:
        self._tasks: dict[str, PluginTask] = {}
        self._order: deque[str] = deque()
        self._listeners: list[TaskListener] = []
        self._keep = keep

    def create(
        self,
        *,
        action: TaskAction,
        package: str,
        module_name: str,
        target: str = "amrita",
    ) -> PluginTask:
        """登记一个新任务。"""
        task = PluginTask(
            id=uuid.uuid4().hex,
            action=action,
            package=package,
            module_name=module_name,
            target=target,
        )
        self._tasks[task.id] = task
        self._order.append(task.id)
        self._prune()
        return task

    def get(self, task_id: str) -> PluginTask | None:
        """按 id 取任务。"""
        return self._tasks.get(task_id)

    def recent(self) -> list[PluginTask]:
        """按登记顺序返回当前保留的任务。"""
        return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def _prune(self) -> None:
        """只保留最近的若干个已完成任务。"""
        while len(self._order) > self._keep:
            oldest = self._order[0]
            task = self._tasks.get(oldest)
            if task is not None and not task.finished:
                break
            self._order.popleft()
            self._tasks.pop(oldest, None)

    def add_listener(self, listener: TaskListener) -> None:
        """注册变更回调（幂等）。"""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: TaskListener) -> None:
        """注销变更回调。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def _notify(self, task: PluginTask) -> None:
        for listener in list(self._listeners):
            try:
                await listener(task)
            except Exception:  # noqa: PERF203 - 单个订阅者出错不应影响其余
                pass

    async def append_line(self, task: PluginTask, line: str) -> None:
        """追加一行输出并通知订阅者。"""
        task.lines.append(line)
        await self._notify(task)

    async def set_running(self, task: PluginTask) -> None:
        """标记为执行中。"""
        task.state = TaskState.RUNNING
        await self._notify(task)

    async def finish(self, task: PluginTask, *, error: str | None = None) -> None:
        """标记结束，并再通知一次终态。"""
        task.error = error
        task.state = TaskState.FAILED if error else TaskState.SUCCEEDED
        task.finished_at = time.time()
        await self._notify(task)


_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """进程内共享的任务管理器。"""
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager
