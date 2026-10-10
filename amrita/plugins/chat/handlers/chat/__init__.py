"""聊天处理器入口（编排）

将原 chat.py 的上帝文件拆分为子包：
- message.py   消息合成/格式化/引用/角色/多模态
- strategy.py  Agent 策略选择与 workflow 装配
- lock.py      pending_mode 锁策略（State 模式）
- streaming.py ChatStreamSender 生命周期与长任务监控
- recovery.py  Panic-Recover 处理
- usage.py     Token 用量统计与持久化

本模块仅保留 entry() 编排主函数。
"""

from __future__ import annotations

from asyncio import CancelledError

from amrita_core import debug_log, logger
from amrita_core.base.backend import BackendSlots
from amrita_core.chatmanager import ChatObject as CoreChatObject
from amrita_core.chatmanager.chat_object import DatabackendOptions
from amrita_core.types import USER_INPUT, Content, Message
from amrita_sense.hook.exception import MatcherException as ChatException
from amrita_sense.hook.matcher import MatcherFactory
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, MessageEvent
from nonebot.exception import MatcherException, NoneBotException, ProcessException
from nonebot.matcher import Matcher
from nonebot_plugin_amrita.memory import CachedUserDataRepository, MemorySchema

from amrita.plugins.chat.backends import ChatMemoryBackend, NoopAbilityBackend
from amrita.plugins.chat.config import config_manager
from amrita.plugins.chat.events import ChatEntryEvent, ChatRequestEvent
from amrita.plugins.chat.runtime import (
    AMRITA_CTX_KEY,
    AmritaBotContext,
    bot_chat_manager,
    pending_chatobj,
)
from amrita.plugins.chat.runtime_session import SessionManager
from amrita.plugins.chat.utils.context import build_train_dict
from amrita.plugins.chat.utils.context_store import (
    MediaExpandBudget,
    expand_media_in_content,
    expand_media_in_messages,
)
from amrita.plugins.chat.utils.lock import get_group_lock, get_private_lock
from amrita.plugins.chat.utils.preset import is_multimodal_enabled, resolve_preset
from amrita.plugins.chat.utils.sql import get_uni_user_id

from .debounce import collect_batch
from .lock import get_pending_mode_strategy
from .message import build_user_input, merge_user_inputs
from .recovery import RecoveryResult, try_panic_recover
from .strategy import build_workflow, select_agent_strategy
from .streaming import StreamSession
from .usage import record_usage

__all__ = ["entry"]

command_prefix = get_driver().config.command_start or "/"


async def entry(event: MessageEvent, matcher: Matcher, bot: Bot):
    """
    聊天处理器入口函数。

    新版流程（初始化与执行完全隔离）：
      1. 会话超时检测与归档（SessionManager）
      2. 加载 memory、合成消息、构建 prompt
      3. 创建 CoreChatObject，通过 hook_kwargs 传递上下文
      4. chat.begin() -> lock -> await chat
      5. 后处理：usage 统计、memory 持久化
    """
    if any(
        event.message.extract_plain_text().strip().startswith(prefix)
        for prefix in command_prefix
        if prefix.strip()
    ):
        matcher.skip()
    session_id = get_uni_user_id(event)
    config = config_manager.config
    cudr = CachedUserDataRepository()

    #  防抖：静默窗口内同一会话同一用户的多条消息合并成一次请求（窗口 <=0 时关闭）
    debounce_window: float = config.function.chat_debounce_window
    events: list[MessageEvent] = [event]
    if debounce_window > 0:
        batch = await collect_batch(event, matcher, debounce_window)
        if batch is None:
            return
        events = batch

    #  阶段 1：加载 memory 与会话管理
    is_group: bool = isinstance(event, GroupMessageEvent)

    #  扩展点：接消息前的观察/否决钩子（ChatEntryEvent.cancel() 可终止本次对话）
    entry_event = ChatEntryEvent(
        event=event,
        matcher=matcher,
        bot=bot,
        session_id=session_id,
        is_group=is_group,
    )
    await MatcherFactory.trigger_event(entry_event)
    if entry_event.cancelled:
        return

    memory: MemorySchema = await cudr.get_memory(
        get_uni_user_id(event),
    )
    data = memory.memory_json

    # 清理异常 message content（仅 Message 需要；ToolResult.content 为 str 无需处理）
    for mem in data.messages:
        if not isinstance(mem, Message):
            continue
        if mem.content is None or isinstance(mem.content, str):
            continue
        mem.content = [i for i in mem.content if isinstance(i, Content)]

    # 会话超时 / 继续恢复
    await SessionManager(
        event=event,
        data=data,
        memory=memory,
        matcher=matcher,
        bot=bot,
        config=config,
    ).manage()
    # manage() 内部可能调用 matcher.finish() 抛出 FinishedException

    #  阶段 2：合成消息（防抖批次内每条消息各自成段，再合并为一条用户输入）
    final_content: USER_INPUT = merge_user_inputs(
        [await build_user_input(ev, bot) for ev in events]
    )
    debug_log(f"合成消息完成，共 {len(events)} 条")

    #  多模态能力同时受预设与 AmritaCore 全局开关约束，只按其中一个判断会错配
    multimodal = await is_multimodal_enabled()

    #  展开只在这里做一次且只作用于**副本**：共享缓存全程只有占位符，中断也不会留下图片内容
    #  本轮输入先展开：图片配额有限，用户刚发的图必须优先于历史图片
    media_budget = MediaExpandBudget(config.context.max_images_per_request)
    final_content = await expand_media_in_content(
        final_content, multimodal=multimodal, budget=media_budget
    )
    memory_view = memory.memory_json.model_copy()
    memory_view.messages = await expand_media_in_messages(
        memory_view.messages, multimodal=multimodal, budget=media_budget
    )

    #  阶段 3：构建策略与 prompt
    strategy = select_agent_strategy(config.llm.agent_strategy)

    # 构建定制化的 system prompt（与 /compact、/session info 共用同一构建逻辑）
    train_dict = await build_train_dict(event, memory, config)

    #  扩展点：请求构建完成后的改写钩子（user_input 与 train 均可在钩子中替换）
    request_event = ChatRequestEvent(
        event=event,
        matcher=matcher,
        bot=bot,
        session_id=session_id,
        user_input=final_content,
        train=train_dict,
    )
    await MatcherFactory.trigger_event(request_event)
    final_content = request_event.user_input
    train_dict = request_event.train

    #  阶段 4：创建 ChatObject
    ctx: AmritaBotContext = {
        "matcher": matcher,
        "bot": bot,
        "event": event,
        "bot_config": config_manager.config,
    }
    chat: CoreChatObject = CoreChatObject(
        train=train_dict,
        user_input=final_content,
        session_id=session_id,
        preset=await resolve_preset(),
        hook_args=(event, matcher, bot),
        hook_kwargs={AMRITA_CTX_KEY: ctx},
        exception_ignored=(ProcessException, MatcherException),
        agent_strategy=strategy,
        workflow=build_workflow(config.llm.agent_workflow),
        chat_man=bot_chat_manager,
        backend=BackendSlots(
            NoopAbilityBackend(),
            ChatMemoryBackend(memory, memory_view),
        ),
        backend_options=DatabackendOptions(
            skip_mcp_fetch=True,
            # skip_tools_fetch 保持默认 False：由数据后端 load_tools 注入 faskill Skills 工具池
            skip_tools_fetch=False,
        ),
    )

    #  阶段 5：设置回调并启动
    stream = StreamSession(
        matcher,
        bot,
        event,
        config,
        chat,
        notify_sec=config.session.session_long_running_notify_seconds,
        is_group=is_group,
    )
    lock = (
        get_group_lock(event.group_id) if is_group else get_private_lock(event.user_id)
    )

    # 按 chat_pending_mode 处理锁占用场景（single / single_with_report / interactive / queue），返回 True 表示已停止本次流程
    if await get_pending_mode_strategy(config.function.chat_pending_mode).handle_locked(
        lock=lock,
        matcher=matcher,
        event=event,
        session_id=session_id,
    ):
        return

    try:
        pending_chatobj[session_id].append(chat)
        try:
            async with lock:
                pending_chatobj[session_id].remove(chat)
                debug_log("继续运行...")

                #  私聊模式后台超时监控：Agent 工作时间超过阈值仍未返回时提示用户如何终止任务
                stream.start_monitor()
                try:
                    async with chat.begin():
                        await chat
                finally:
                    await stream.stop_monitor()

                stream.mark_received()
                await stream.send_final()
        finally:
            # 兜底：异常时清理 pending
            if chat in pending_chatobj[session_id]:
                pending_chatobj[session_id].remove(chat)

    except BaseException as e:
        if isinstance(e, (NoneBotException, ChatException)):
            raise

        if isinstance(e, CancelledError):
            return

        # Panic-Recover：触发事件让外部处理器决定是否恢复；恢复成功继续剩余管线（含 COMMIT_MEMORY）
        result = await try_panic_recover(chat, e, config)
        if result is RecoveryResult.RECOVERED:
            # 恢复成功：走正常收尾（send_final；usage 统计由外层 finally 完成）
            stream.mark_received()
            await stream.send_final()
            return
        if result is RecoveryResult.ABANDONED:
            return

        await matcher.send("出错了稍后试试吧（错误已反馈）")
        logger.opt(exception=e, colors=True, raw=True).exception(
            "程序发生了未捕获的异常"
        )
    finally:
        await record_usage(chat, event, cudr)
