"""Chat 插件的公开事件与扩展点。

事件派发内核是 AmritaSense 的 ``EventRegistry`` + ``MatcherFactory.trigger_event``。
本模块把所有可由外部订阅的事件收敛到同一个 import 面，并提供便捷注册器。

注册示例::

    from amrita.plugins.chat.events import ChatRequestEvent, on_chat_request

    @on_chat_request()
    async def rewrite(event: ChatRequestEvent) -> None:
        event.user_input = "改写后的输入"

``block`` 语义（AmritaSense 原生，容易踩坑）：``Matcher(block=True)`` 表示该处理器
跑完就结束整条事件链，而 ``block`` 的**默认值就是 True**；观察型钩子必须显式传
``block=False``。本模块的便捷注册器默认即为 ``block=False``。

处理器内部还可以用 ``matcher.pass_event()`` 跳过自己、用
``matcher.stop_process()`` 终止整条事件链。参数注入按**类型**匹配事件与
NoneBot 对象（``Matcher`` / ``MessageEvent`` / ``Bot``），因此参数名可自取。

除本模块自定义的事件外，AmritaCore 的 agent 步骤事件
（``agent.step_intro`` / ``agent.step_leave`` / ``agent.step_iteration`` /
``agent.tool_call`` / ``agent.tool_return``）也在此重导出并配了便捷注册器，
插件不必再手写这些字符串常量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amrita_core import BillingRecord, UniResponseUsage
from amrita_core.builtins.agent.events import (
    StepAbortError,
    StepIntroEvent,
    StepIterationEvent,
    StepLeaveEvent,
    StepToolCallEvent,
    StepToolReturnEvent,
)
from amrita_core.types import USER_INPUT
from amrita_sense.hook.event import BaseEvent
from amrita_sense.hook.matcher import Matcher as HookMatcher
from amrita_sense.hook.on import on_event
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.adapters.onebot.v11.event import PokeNotifyEvent
from nonebot.matcher import Matcher

from .panic_recover import ChatPanicRecoverEvent
from .utils.stream_sender import NoMessageSendError, SendMessageEvent

#  AmritaCore 的 agent 事件类型字符串（定义于 amrita_core.builtins.agent.events）
AGENT_STEP_INTRO = "agent.step_intro"
AGENT_STEP_LEAVE = "agent.step_leave"
AGENT_STEP_ITERATION = "agent.step_iteration"
AGENT_TOOL_CALL = "agent.tool_call"
AGENT_TOOL_RETURN = "agent.tool_return"


class PokeSendError(BaseException):
    """钩子抛出以静默拦截 poke 回复发送（不回复、不报错）"""


class PokeSendMessageEvent(BaseEvent[str]):
    """poke 回复发送前触发的事件（与 chat 的 ``SendMessageEvent`` 完全独立）

    ``content``: 构建好的 MessageSegment，钩子可直接修改或替换
    """

    def __init__(
        self,
        content: Message,
        *,
        event: PokeNotifyEvent,
        matcher: Matcher,
        bot: Bot,
    ):
        self.content = content
        self.event = event
        self.matcher = matcher
        self.bot = bot

    def get_event_type(self) -> str:
        return "POKE_SEND_MESSAGE"

    @property
    def event_type(self) -> str:
        return "POKE_SEND_MESSAGE"


@dataclass
class ChatEntryEvent(BaseEvent[str]):
    """进入 chat 处理流程前触发，早于会话超时检查与消息合成。

    适合做「接消息前」的观察、记账或否决：调用 :meth:`cancel` 后 ``entry()``
    直接返回，不进入后续任何阶段（也不会回复）。
    """

    EVENT_TYPE = "CHAT_ENTRY"

    event: MessageEvent
    matcher: Matcher
    bot: Bot
    session_id: str
    is_group: bool
    _cancelled: bool = field(default=False, init=False, repr=False)

    def cancel(self) -> None:
        """否决本次对话，``entry()`` 不再继续。"""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def get_event_type(self) -> str:
        return self.EVENT_TYPE

    @property
    def event_type(self) -> str:
        return self.EVENT_TYPE


@dataclass
class ChatRequestEvent(BaseEvent[str]):
    """消息合成完成、构建 ``CoreChatObject`` 之前触发。

    ``user_input`` 与 ``train`` 可原地修改，改动直接生效于本次请求；
    这是改写用户输入或注入 system prompt 字段的唯一挂载点。
    """

    EVENT_TYPE = "CHAT_REQUEST"

    event: MessageEvent
    matcher: Matcher
    bot: Bot
    session_id: str
    user_input: USER_INPUT
    train: dict[str, Any]

    def get_event_type(self) -> str:
        return self.EVENT_TYPE

    @property
    def event_type(self) -> str:
        return self.EVENT_TYPE


@dataclass
class ChatUsageRecordedEvent(BaseEvent[str]):
    """一次对话的 token 用量统计落库后触发。

    计费、配额、审计等扩展应挂在这里：``usage`` 为 ``None`` 表示 provider 未
    上报用量（本次只计次不计 token）；``billing`` 是 Core 逐次请求写入
    ``MemoryModel.billing`` 的账目快照，预设未声明 ``rate`` 时只有 token 数。
    """

    EVENT_TYPE = "CHAT_USAGE_RECORDED"

    event: MessageEvent
    session_id: str
    usage: UniResponseUsage | None
    billing: list[BillingRecord]

    def get_event_type(self) -> str:
        return self.EVENT_TYPE

    @property
    def event_type(self) -> str:
        return self.EVENT_TYPE


@dataclass
class SessionCompactEvent(BaseEvent[str]):
    """会话上下文被压缩（``/session compact``）后触发。

    ``before_count`` / ``after_count`` 为压缩前后的消息条数，
    ``summary_usage`` 是摘要调用本身的用量（单独记账，不计入会话）。
    """

    EVENT_TYPE = "SESSION_COMPACT"

    event: MessageEvent
    matcher: Matcher
    session_id: str
    before_count: int
    after_count: int
    before_tokens: int
    budget: int
    summary_usage: UniResponseUsage

    def get_event_type(self) -> str:
        return self.EVENT_TYPE

    @property
    def event_type(self) -> str:
        return self.EVENT_TYPE


def on_chat_entry(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 :class:`ChatEntryEvent` 处理器。"""
    return on_event(ChatEntryEvent.EVENT_TYPE, priority, block)


def on_chat_request(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 :class:`ChatRequestEvent` 处理器。"""
    return on_event(ChatRequestEvent.EVENT_TYPE, priority, block)


def on_chat_usage_recorded(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 :class:`ChatUsageRecordedEvent` 处理器。"""
    return on_event(ChatUsageRecordedEvent.EVENT_TYPE, priority, block)


def on_session_compact(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 :class:`SessionCompactEvent` 处理器。"""
    return on_event(SessionCompactEvent.EVENT_TYPE, priority, block)


def on_agent_step_intro(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 ``agent.step_intro`` 处理器，可改 ``override_phase``。"""
    return on_event(AGENT_STEP_INTRO, priority, block)


def on_agent_step_leave(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 ``agent.step_leave`` 处理器，可改 ``override_verb`` / ``override_object``。"""
    return on_event(AGENT_STEP_LEAVE, priority, block)


def on_agent_step_iteration(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 ``agent.step_iteration`` 处理器，可置 ``end_step`` 提前结束本轮。"""
    return on_event(AGENT_STEP_ITERATION, priority, block)


def on_tool_call(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 ``agent.tool_call`` 处理器（工具执行前）。

    可改写 ``arguments``、置 ``cancel``，或抛出 :class:`StepAbortError`
    取消本次调用（调用方会返回 ``"Cancelled: ..."`` 而不执行工具）。
    """
    return on_event(AGENT_TOOL_CALL, priority, block)


def on_tool_return(priority: int = 10, block: bool = False) -> HookMatcher:
    """注册 ``agent.tool_return`` 处理器（工具返回后）。

    可改写 ``result``（模型看到的内容）、置 ``skip_append`` 跳过写回，
    或抛出 :class:`StepAbortError`。
    """
    return on_event(AGENT_TOOL_RETURN, priority, block)


__all__ = [
    "AGENT_STEP_INTRO",
    "AGENT_STEP_ITERATION",
    "AGENT_STEP_LEAVE",
    "AGENT_TOOL_CALL",
    "AGENT_TOOL_RETURN",
    "ChatEntryEvent",
    "ChatPanicRecoverEvent",
    "ChatRequestEvent",
    "ChatUsageRecordedEvent",
    "NoMessageSendError",
    "PokeSendError",
    "PokeSendMessageEvent",
    "SendMessageEvent",
    "SessionCompactEvent",
    "StepAbortError",
    "StepIntroEvent",
    "StepIterationEvent",
    "StepLeaveEvent",
    "StepToolCallEvent",
    "StepToolReturnEvent",
    "on_agent_step_intro",
    "on_agent_step_iteration",
    "on_agent_step_leave",
    "on_chat_entry",
    "on_chat_request",
    "on_chat_usage_recorded",
    "on_session_compact",
    "on_tool_call",
    "on_tool_return",
]
