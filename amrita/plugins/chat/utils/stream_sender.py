"""聊天流式消息发送器

将流式消息的处理与最终响应的发送抽离为独立类：

- 流式元信息消息（MessageWithMetadata）经 _ReasoningCollector 收集/过滤后转发
- 最终响应发送前触发 `SendMessageEvent` 钩子，允许修改 MessageSegment
  或抛出 `NoMessageSendError` 静默拦截（不回复、不报错）
"""

from __future__ import annotations

import asyncio
import random
from io import StringIO
from typing import TYPE_CHECKING, Any

from amrita_core.contents import (
    ImageMessage,
    MessageWithMetadata,
    StringMessageContent,
)
from amrita_sense.hook.event import BaseEvent
from amrita_sense.hook.matcher import MatcherFactory
from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from amrita.utils.admin import send_to_admin
from amrita.utils.send import send_forward_msg

from ..config import Config
from .functions import split_message_into_chats
from .reasoning_summary import SummaryLimits, summarize_reasoning

if TYPE_CHECKING:
    from amrita_core.base.adapter import COMPLETION_RETURNING
    from amrita_core.chatmanager import ChatObject as CoreChatObject
    from nonebot.adapters.onebot.v11 import Bot, MessageEvent
    from nonebot.matcher import Matcher


class NoMessageSendError(BaseException):
    """钩子抛出以静默拦截最终消息发送（不回复、不报错）"""


class SendMessageEvent(BaseEvent[str]):
    """最终消息发送前触发的事件

    content: 构建好的 MessageSegment，钩子可直接修改或替换
    """

    def __init__(
        self,
        content: Message,
        *,
        chat: CoreChatObject,
        event: MessageEvent,
        matcher: Matcher,
        bot: Bot,
    ):
        self.content = content
        self.chat = chat
        self.event = event
        self.matcher = matcher
        self.bot = bot

    def get_event_type(self) -> str:
        return "SEND_MESSAGE"

    @property
    def event_type(self) -> str:
        return "SEND_MESSAGE"


def _split_forward_chunks(text: str, min_chunk: int) -> list[str]:
    """按连续换行拆分合并转发分块

    以 "\n\n" 为分隔拆分；若某块长度不足 min_chunk，则与下一块合并。
    全部块都满足 min_chunk 或整体不足时返回单块。
    """
    raw_chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    if not raw_chunks:
        return [text]
    chunks: list[str] = []
    current = ""
    for chunk in raw_chunks:
        if not current:
            current = chunk
        elif len(current) < min_chunk:
            current += "\n\n" + chunk
        else:
            chunks.append(current)
            current = chunk
    if current:
        chunks.append(current)
    return chunks


class _ReasoningCollector:
    """只按"是否还在思考"切段，避免同一段思考被 extra_type 变化拆成多条消息。"""

    def __init__(self) -> None:
        self.buffer = StringIO()

    def flush(self) -> str | None:
        text = self.buffer.getvalue()
        self.buffer = StringIO()
        return text or None

    def write(self, content: str) -> None:
        """追加一个思考片段，不在片段之间切分"""
        self.buffer.write(content)


class ChatStreamSender:
    """流式消息发送器

    用法:
        sender = ChatStreamSender(matcher, bot, event, config, chat)
        chat.io_stream.set_callback_func(sender.handle)
        ...
        await sender.send_final(response)   # 触发钩子后发送最终响应
    """

    def __init__(
        self,
        matcher: Matcher,
        bot: Bot,
        event: MessageEvent,
        config: Config,
        chat: CoreChatObject,
    ):
        self._matcher = matcher
        self._bot = bot
        self._event = event
        self._config = config
        self._chat = chat
        self._reasoning = _ReasoningCollector()
        self._blocked = False  # cookie 熔断后置位，send_final 静默跳过

    async def _flush_reasoning(self) -> None:
        """把累积的思考整段发出；开启摘要时先压缩，失败回退原文。"""
        text = self._reasoning.flush()
        if not text:
            return
        if self._config.meta.reasoning_summary:
            usage = getattr(getattr(self._chat, "_di_resp", None), "usage", None)
            meta = self._config.meta
            limits = SummaryLimits(
                max_chars=meta.reasoning_summary_max_chars,
                input_chars=meta.reasoning_summary_input_chars,
                max_output=meta.reasoning_summary_max_output,
                timeout=meta.reasoning_summary_timeout_seconds,
            )
            if summary := await summarize_reasoning(text, usage, limits):
                text = summary
        await self._send_reasoning(text)

    async def _send_reasoning(self, text: str) -> None:
        """发送思考块：过长时改走合并转发，避免单条消息超限。"""
        threshold = self._config.function.forward_threshold
        if threshold > 0 and len(text) > threshold:
            parts = [
                MessageSegment.text(part)
                for part in _split_forward_chunks(
                    text, self._config.function.forward_min_chunk
                )
            ]
            await send_forward_msg(
                self._bot,
                self._event,
                name="Amrita",
                uin=str(self._event.self_id),
                msgs=parts,
            )
            return
        #  模型输出可能带 CQ 码，按文本段发送，避免被解析成提及或图片
        await self._matcher.send(MessageSegment.text(f"💭 {text}"))

    async def handle(self, message: "COMPLETION_RETURNING") -> None:
        """流式消息回调：处理元信息消息、收集思考块、转发文本/图片"""
        if isinstance(message, str):
            return
        if isinstance(message, MessageWithMetadata):
            await self._handle_metadata(message)
            return
        if isinstance(message, StringMessageContent):
            await self._flush_reasoning()
            await self._matcher.send(message.get_content())
            return
        if isinstance(message, ImageMessage):
            await self._flush_reasoning()
            await self._matcher.send(MessageSegment.image(await message.get_image()))
            return
        # 未知类型：保持原有直接转发行为
        await self._matcher.send(str(message))

    async def _handle_metadata(self, message: MessageWithMetadata) -> None:
        meta = self._config.meta
        metadata: dict[str, Any] = dict(message.metadata)
        mtype = metadata.get("type", "")
        extra_type = metadata.get("extra_type")
        #  原生 cot_chunk 与框架包装的 reasoning chunk 都要算思考，
        #  否则原生思考会被当成正文 flush 掉，框架片段则被切成半句
        is_reasoning_chunk = mtype == "reasoning_chunk" or (
            mtype == "text" and extra_type in ("reasoning_chunk", "cot_chunk")
        )
        if is_reasoning_chunk and meta.enable and meta.stream_reasoning:
            # 只做累积，等这一轮思考结束（下一条非思考消息或本轮结束）再整段发送
            self._reasoning.write(message.content)
            return
        # 非思考块消息：先 flush 累积的思考块再处理
        await self._flush_reasoning()
        match mtype:
            case "system":
                if metadata.get("extra_type") == "tool_call_limit":
                    await self._matcher.send(
                        "⚠️ 已达工具调用上限，接下来会基于已获取的信息作答。"
                    )
                else:
                    await self._matcher.send(message.content)
            case "reasoning":
                # 框架整段思考块（pre_resolve）
                if meta.enable and meta.reasoning:
                    await self._matcher.send(f"💭 {message.content}")
            case "tool_prediction":
                if meta.enable and meta.tool_call:
                    await self._matcher.send("⏩ 优化了工具选择")
            case "middle_message":
                await self._matcher.send(f"💬 {message.content}")
            case "function_call":
                # content 可能是工具生命周期的机器文案，也可能带模型正文
                function_name = metadata.get("function_name")
                err = metadata.get("err")
                text = message.content.strip()
                lifecycle = (
                    text.startswith("Calling function ")
                    or text.startswith("Called tool ")
                    or (bool(function_name) and text == f"Error: {function_name} failed.")
                )
                if meta.enable and text and not lifecycle:
                    await self._matcher.send(MessageSegment.text(f"💬 {text}"))
                if err is not None:
                    logger.opt(exception=err, colors=True, raw=True).exception(
                        f"Tool {function_name} execution failed: {err}"
                    )
                if metadata.get("is_done") and meta.enable and meta.tool_call:
                    if err is not None:
                        await self._matcher.send(f"ERR: {function_name} 执行失败")
                    else:
                        await self._matcher.send(f"调用了工具：{function_name}")
            case "step":
                # Step 生命周期消息，按 extra_type 粒度控制
                if (
                    meta.enable
                    and extra_type is not None
                    and getattr(meta.step, extra_type, False)
                ):
                    await self._matcher.send(f"🪜 {message.content}")
            case "reflection":
                # 反思结果：self_check/contradiction_check/completeness_check
                if meta.enable and meta.reflection:
                    detail = metadata.get("detail")
                    text = f"🔍 {message.content}"
                    if detail:
                        text += f"\n{detail}"
                    await self._matcher.send(text)
            case "skill_call":
                # 技能触发通知（由 skills 模块在技能工具被调用时推送）
                if meta.enable and meta.skill_trigger:
                    await self._matcher.send(f"🧠 {message.content}")
            case "text":
                if (
                    extra_type == "structured_reasoning_step"
                    and meta.enable
                    and meta.reasoning
                ):
                    await self._matcher.send(message.content)
            case "error":
                if metadata.get("extra_type") == "cookie":
                    await self._handle_cookie_error()
                    return
                error = metadata.get("error")
                logger.opt(exception=error, colors=True, raw=True).exception(
                    f"有错误发生:{error}"
                )
                if meta.enable and meta.error_report:
                    await self._matcher.send(f"❌ {message.content}")

    async def _handle_cookie_error(self) -> None:
        """cookie 泄露：通知管理员并熔断（不再发送最终响应）"""
        chat = self._chat
        response_content = ""
        if (resp := chat._di_resp.response) is not None:
            response_content = resp.content or ""
        await send_to_admin(
            f"安全警告：用户请求导致了可能的Prompt泄露。已在response检测到cookie泄露，请检查！\n用户请求：\n{chat.user_input!s}\n模型模型输出：\n{response_content!s}"
        )
        self._blocked = True
        await self._matcher.send(random.choice(self._config.llm.block_msg))

    async def send_final(self, content: str) -> None:
        """发送最终响应：先触发 SendMessageEvent 钩子，再发送

        发送策略：
        - 文本超过 200 字符：改用合并转发（分句拆分节点）
        - nature_chat_style：按分句规则拆分发送（带随机间隔）
        - 否则引用回复一次性发送

        Args:
            content: 模型最终回复文本

        Raises:
            NoMessageSendError: 钩子拦截，静默不发送
        """
        if self._blocked:
            return
        # 发送前 flush 残留思考块
        await self._flush_reasoning()

        # 构建 MessageSegment（引用回复）
        message: Message = MessageSegment.reply(
            self._event.message_id
        ) + MessageSegment.text(content)

        # 触发钩子：允许修改或拦截
        ev = SendMessageEvent(
            message,
            chat=self._chat,
            event=self._event,
            matcher=self._matcher,
            bot=self._bot,
        )
        await MatcherFactory.trigger_event(ev, exception_ignored=(NoMessageSendError,))

        # 发送（与 send_response 行为一致）
        final_text = ev.content.extract_plain_text()
        forward_threshold = self._config.function.forward_threshold
        if forward_threshold > 0 and len(final_text) > forward_threshold:
            # 超长响应改用合并转发：按连续换行拆分，每块至少 min_chunk 字符
            min_chunk = self._config.function.forward_min_chunk
            parts = [
                MessageSegment.text(part)
                for part in _split_forward_chunks(final_text, min_chunk)
            ]
            await send_forward_msg(
                self._bot,
                self._event,
                name="Amrita",
                uin=str(self._event.self_id),
                msgs=parts,
            )
        elif not self._config.function.nature_chat_style:
            await self._matcher.send(ev.content)
        elif response_list := split_message_into_chats(final_text):
            for part in response_list:
                await self._matcher.send(MessageSegment.text(part))
                await asyncio.sleep(
                    random.randint(1, 3) + (len(part) // random.randint(80, 100))
                )
