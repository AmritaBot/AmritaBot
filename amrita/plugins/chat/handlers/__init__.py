"""handlers 包统一导出

所有事件处理器（命令 / 消息 / 通知）在此收敛，
供 matcher_manager 数据驱动路由表注册使用。
"""

from .add_notices import add_notices
from .chat import entry as chat
from .chat_switch import chat as chat_switch
from .chatobj import chatobj_manage
from .debug_switchs import debug_switchs
from .insights import insights
from .mcp import mcp_command
from .model import model
from .poke_event import poke_event
from .prompt import prompt
from .recall import recall
from .session_cmd import session

__all__ = [
    "add_notices",
    "chat",
    "chat_switch",
    "chatobj_manage",
    "debug_switchs",
    "insights",
    "mcp_command",
    "model",
    "poke_event",
    "prompt",
    "recall",
    "session",
]
