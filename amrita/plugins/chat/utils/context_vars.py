"""跨异步任务传递的会话上下文变量。"""

from contextvars import ContextVar

#  当前运行中的会话 ID；工具钩子拿不到事件里的会话，只能靠上下文传递
current_uni_id: ContextVar[str] = ContextVar("amrita_uni_id", default="")
