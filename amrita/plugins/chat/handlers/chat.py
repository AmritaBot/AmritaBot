"""聊天处理器模块"""

import asyncio
import contextlib
from asyncio import CancelledError
from datetime import datetime

from amrita_core import (
    PresetManager,
    TextContent,
    UniResponseUsage,
    debug_log,
    logger,
    text_generator,
)
from amrita_core.base.backend import BackendSlots
from amrita_core.builtins.agent import (
    HybridReActAgentStrategy,
    NoActionAgentStrategy,
    ReActAgentStrategy,
)
from amrita_core.chatmanager import (
    ChatObject as CoreChatObject,
)
from amrita_core.chatmanager import (
    _step_workflow_rendered,
)
from amrita_core.chatmanager.chat_object import DatabackendOptions
from amrita_core.tokenizer import hybrid_token_count
from amrita_core.types import USER_INPUT, Content, ImageContent, ImageUrl
from amrita_core.utils import gather_usage
from amrita_sense.hook.exception import MatcherException as ChatException
from amrita_sense.hook.matcher import MatcherFactory
from beartype.typing import Sequence
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import (
    Bot,
)
from nonebot.adapters.onebot.v11.event import (
    GroupMessageEvent,
    MessageEvent,
    Reply,
)
from nonebot.exception import MatcherException, NoneBotException, ProcessException
from nonebot.matcher import Matcher
from nonebot_plugin_amrita.database import (
    InsightsModel,
)
from nonebot_plugin_amrita.memory import CachedUserDataRepository, MemorySchema

from amrita.plugins.chat.backends import ChatMemoryBackend, NoopAbilityBackend
from amrita.plugins.chat.config import ConfigManager, config_manager
from amrita.plugins.chat.panic_recover import ChatPanicRecoverEvent
from amrita.plugins.chat.runtime import (
    AMRITA_CTX_KEY,
    AmritaBotContext,
    bot_chat_manager,
    pending_chatobj,
)
from amrita.plugins.chat.runtime_session import SessionManager
from amrita.plugins.chat.utils.context import build_train_dict
from amrita.plugins.chat.utils.functions import (
    get_friend_name,
    synthesize_message,
)
from amrita.plugins.chat.utils.libchat import add_usage
from amrita.plugins.chat.utils.lock import get_group_lock, get_private_lock
from amrita.plugins.chat.utils.sql import (
    get_uni_user_id,
)
from amrita.plugins.chat.utils.stream_sender import ChatStreamSender, NoMessageSendError

command_prefix = get_driver().config.command_start or "/"


def escape_content(raw: str) -> str:
    """
    转义用户输入中可能与 legacy 消息格式冲突的字符。

    legacy 格式使用 [...] 标记用户身份、说: 标记发言，
    用户输入中出现相同字符时全角替换以避免 LLM 误解析。
    """
    return raw.replace("[", "\uff3b").replace("]", "\uff3d").replace("说:", "说：")


def escape_xml(raw: str) -> str:
    """
    转义用户输入中可能与 XML 消息格式冲突的字符。

    < > & 替换为 XML 实体，防止 injection。
    """
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_msg_legacy(role: str, name: str, uid: str, content: str) -> str:
    """legacy 格式：方括号标记，紧凑风格"""
    safe_content = escape_content(content)
    safe_name = escape_content(name)
    if role:
        return f"[{role}][{safe_name}（{uid}）]说:{safe_content}"
    return f"[{safe_name}（{uid}）]说:{safe_content}"


def format_msg_xml(role: str, name: str, uid: str, content: str) -> str:
    """XML 格式：标签标记，结构清晰，天然支持多行"""
    safe_content = escape_xml(content)
    safe_name = escape_xml(name)
    attrs = f' role="{role}"' if role else ""
    return f'<msg{attrs} name="{safe_name}" uid="{uid}">\n{safe_content}\n</msg>'


async def handle_reply(
    reply: Reply, bot: Bot, group_id: int | None, content: str
) -> str:
    """处理引用消息：
    - 提取引用消息的内容和时间信息。
    - 格式化为可读的引用内容。

    Args:
        reply: 回复消息
        bot: Bot实例
        group_id: 群组ID（私聊为None）
        content: 原始内容

    Returns:
        格式化后的内容
    """
    if not reply.sender.user_id:
        return content
    dt_object = datetime.fromtimestamp(reply.time)
    weekday = dt_object.strftime("%A")
    formatted_time = dt_object.strftime("%Y-%m-%d %I:%M:%S %p")
    role = (
        f"{await get_user_role(bot, group_id, reply.sender.user_id)}"
        if group_id
        else ""
    )

    reply_content = await synthesize_message(reply.message, bot)
    safe_name = reply.sender.nickname or ""
    msg_type = config_manager.config.function.message_type

    if msg_type == "xml":
        safe_content = escape_xml(reply_content)
        safe_name = escape_xml(safe_name)
        # 用户消息内容也需要转义，因为 downstream format_msg_xml
        # 在检测到已有 <ref> 后会跳过二次转义
        safe_user_content = escape_xml(content)
        result = (
            f"{safe_user_content}\n"
            f'<ref name="{safe_name}" uid="{reply.sender.user_id}">\n'
            f"  <time>{formatted_time} {weekday}</time>\n"
            f"  <content>{safe_content}</content>\n"
            f"</ref>"
        )
    else:
        safe_content = escape_content(reply_content)
        safe_name = escape_content(safe_name)
        result = f"{content}\n<MESSAGE_REFERED>\n{formatted_time} {weekday} {role}{safe_name}（QQ:{reply.sender.user_id}）说：{safe_content}\n</MESSAGE_REFERED>"
    debug_log(f"处理引用消息完成: {result[:50]}..")
    return result


def get_reply_pics(event: MessageEvent) -> list[ImageContent]:
    """获取引用消息中的图片内容

    Returns:
        图片内容列表
    """
    if reply := event.reply:
        msg = reply.message
        images = [
            ImageContent(image_url=ImageUrl(url=url))
            for seg in msg
            if seg.type == "image" and (url := seg.data.get("url")) is not None
        ]
        debug_log(f"获取引用图片完成，共 {len(images)} 张")
        return images
    return []


async def get_user_role(bot: Bot, group_id: int, user_id: int) -> str:
    """获取用户在群聊中的身份（群主、管理员或普通成员）。

    Args:
        group_id: 群组ID
        user_id: 用户ID

    Returns:
        用户角色字符串
    """
    role_data = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    role = role_data["role"]
    role_str = {"admin": "群管理员", "owner": "群主", "member": "普通成员"}.get(
        role, "[获取身份失败]"
    )
    debug_log(f"获取用户角色完成: {role_str}")
    return role_str


def synthesize_message_to_msg(
    event: MessageEvent,
    role: str,
    user_name: str,
    user_id: str,
    content: str,
) -> Sequence[Content] | str:
    """将消息转换为Message

    根据配置和多模态支持情况，将事件消息转换为适当的格式，
    支持文本和图片内容的组合。

    Args:
        event: 消息事件
        role: 用户角色
        date: 时间戳
        user_name: 用户名
        user_id: 用户ID
        content: 消息内容

    Returns:
        转换后的消息内容
    """
    is_multimodal: bool = (
        any(
            (
                (PresetManager().get_preset(preset)).config.multimodal
                if preset != "default"
                else ConfigManager().config.default_preset.config.multimodal
            )
            for preset in [
                config_manager.config.preset,
                *config_manager.config.preset_extension.backup_preset_list,
            ]
        )
        # or len(config_manager.config.preset_extension.multi_modal_preset_list) > 0
    )

    if config_manager.config.parse_segments:
        if config_manager.config.function.message_type == "xml":
            # handle_reply 在 XML 模式下已对 content 做了 escape_xml，
            # 且 content 中可能包含 <ref> 标签（已转义好的引用内容），
            # 因此不能再次经过 format_msg_xml -> escape_xml 导致双重转义
            if "\n<ref" in content:
                safe_name = escape_xml(str(user_name))
                attrs = f' role="{role}"' if role else ""
                body = f'<msg{attrs} name="{safe_name}" uid="{user_id}">\n{content}\n</msg>'
            else:
                body = format_msg_xml(role, str(user_name), str(user_id), content)
        else:
            body = format_msg_legacy(role, str(user_name), str(user_id), content)
        text: Sequence[Content] | str = (
            [TextContent(text=body)]
            + [
                ImageContent(image_url=ImageUrl(url=seg.data["url"]))
                for seg in event.message
                if seg.type == "image" and seg.data.get("url")
            ]
            if is_multimodal
            else body
        )
    else:
        text = event.message.extract_plain_text()
    return text


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
    config = ConfigManager().config
    cudr = CachedUserDataRepository()

    #  阶段 1：加载 memory 与会话管理
    is_group: bool = isinstance(event, GroupMessageEvent)
    memory: MemorySchema = await cudr.get_memory(
        get_uni_user_id(event),
    )
    data = memory.memory_json

    # 清理异常 message content
    for mem in data.messages:
        if mem.content is None or isinstance(mem.content, str):
            continue
        else:
            mem.content = [i for i in mem.content if isinstance(i, Content)]  # pyright: ignore[reportAttributeAccessIssue] # 这不是str，这一定是list

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

    #  阶段 2：合成消息
    content: USER_INPUT = await synthesize_message(event.get_message(), bot)
    debug_log(f"合成消息完成: {content}")

    if content.strip() == "":
        content = ""
    if event.reply:
        group_id = event.group_id if is_group else None
        debug_log("处理引用消息..")
        content = await handle_reply(event.reply, bot, group_id, content)

    reply_pics = get_reply_pics(event)
    debug_log(f"获取引用图片完成，共 {len(reply_pics)} 张")

    if is_group:
        debug_log("处理群聊消息")
        user_name = (
            (
                await bot.get_group_member_info(
                    group_id=event.group_id, user_id=event.user_id
                )
            )["nickname"]
            if not config.function.use_user_nickname
            else event.sender.nickname
        )
    else:
        debug_log("处理私聊消息")
        user_name = await get_friend_name(event.user_id, bot=bot)
    role = await get_user_role(bot, event.group_id, event.user_id) if is_group else ""
    content = synthesize_message_to_msg(
        event, role, str(user_name), str(event.user_id), content
    )
    if isinstance(content, list):
        content.extend(reply_pics)

    #  阶段 3：构建策略与 prompt
    match config.llm.agent_strategy:
        case "react":
            strategy = ReActAgentStrategy
        case "hybrid-react":
            strategy = HybridReActAgentStrategy
        case "no-action":
            strategy = NoActionAgentStrategy
        case _:
            raise ValueError(f"Invalid agent strategy: {config.llm.agent_strategy}")

    # 构建定制化的 system prompt（与 /compact、/session info 共用同一构建逻辑）
    train_dict = build_train_dict(event, memory, config)

    #  阶段 4：创建 ChatObject
    ctx: AmritaBotContext = {
        "matcher": matcher,
        "bot": bot,
        "event": event,
        "bot_config": ConfigManager().config,
    }
    chat: CoreChatObject = CoreChatObject(
        train=train_dict,
        user_input=content,
        session_id=session_id,
        preset=await ConfigManager().get_preset(config.preset),
        hook_args=(event, matcher, bot),
        hook_kwargs={AMRITA_CTX_KEY: ctx},
        exception_ignored=(ProcessException, MatcherException),
        agent_strategy=strategy,
        workflow=(
            _step_workflow_rendered
            if config.llm.agent_workflow == "step-react"
            else None
        ),
        chat_man=bot_chat_manager,
        backend=BackendSlots(
            NoopAbilityBackend(),
            ChatMemoryBackend(memory),
        ),
        backend_options=DatabackendOptions(
            skip_mcp_fetch=True,
            skip_tools_fetch=True,
            skip_presets_fetch=True,
        ),
    )

    #  阶段 5：设置回调并启动
    stream_sender = ChatStreamSender(matcher, bot, event, config, chat)
    chat.io_stream.set_callback_func(stream_sender.handle)

    lock = (
        get_group_lock(event.group_id) if is_group else get_private_lock(event.user_id)
    )

    match config.function.chat_pending_mode:
        case "single":
            if lock.locked():
                debug_log("聊天已被锁定，跳过")
                return matcher.stop_propagation()
        case "single_with_report":
            if lock.locked():
                debug_log("聊天已被锁定，发送报告")
                await matcher.finish("聊天任务正在处理中，请稍后再试")
        case "interactive":
            if lock.locked():
                # 锁被占用：不排队不跳过，通过反向流把本条消息推给正在运行的 ChatObject
                # Core 在下一个 Step 边界将其消费为 [peer message] 追加到上下文
                debug_log("聊天已被锁定，推送给正在运行的 ChatObject")
                running_chat = next(
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
                return matcher.stop_propagation()

    try:
        pending_chatobj[session_id].append(chat)
        try:
            async with lock:
                pending_chatobj[session_id].remove(chat)
                debug_log("继续运行...")

                #  私聊模式后台超时监控：若 Agent 工作时间超过阈值仍未返回，
                #  发送提示告知用户如何终止任务
                response_received = False
                notify_sec = config.session.session_long_running_notify_seconds
                if not is_group and notify_sec > 0:

                    async def _notify_long_running() -> None:
                        await asyncio.sleep(notify_sec)
                        if not response_received:
                            await matcher.send(
                                "💡Agent已工作了一会儿，但还是没有给出答案，"
                                "使用/chatobj kill终止当前任务。"
                            )

                    monitor_task = asyncio.create_task(_notify_long_running())
                else:
                    monitor_task = None

                try:
                    async with chat.begin():
                        await chat
                finally:
                    if monitor_task and not monitor_task.done():
                        monitor_task.cancel()
                        with contextlib.suppress(CancelledError):
                            await monitor_task

                response_received = True
                if chat._di_resp.response is not None:
                    # 钩子可能抛出 NoMessageSendError 静默拦截，不发送、不报错
                    with contextlib.suppress(NoMessageSendError):
                        await stream_sender.send_final(chat._di_resp.response.content)
        finally:
            # 兜底：异常时清理 pending
            if chat in pending_chatobj[session_id]:
                pending_chatobj[session_id].remove(chat)

    except BaseException as e:
        if isinstance(e, (NoneBotException, ChatException)):
            raise

        if isinstance(e, CancelledError):
            return

        # Panic-Recover：解释器已 dump（panic 现场保留在 interpreter 上），
        # 触发事件让外部处理器决定是否恢复。恢复成功则继续执行剩余管线
        # （含 COMMIT_MEMORY 记忆提交）；未恢复则走旧路径，不提交记忆。
        panic_event = ChatPanicRecoverEvent(
            chat=chat,
            interpreter=chat._interpreter,
            exception=e,
            context_wrap=chat._di_working.context_wrap,
        )
        await MatcherFactory.trigger_event(
            panic_event,
            config,
            chat,
            slot=chat.slot,
            exception_ignored=(ProcessException, MatcherException),
        )
        if panic_event.should_continue:
            try:
                # Sense 原生 panic-recover：再次驱动解释器，从崩溃节点继续
                await chat._interpreter.run()
            except BaseException as e2:
                if not isinstance(e2, CancelledError):
                    logger.opt(exception=e2, colors=True, raw=True).exception(
                        "Panic-Recover 后解释器再次异常，已放弃本次任务"
                    )
                return
            # 恢复成功：走正常收尾（send_final；usage 统计由外层 finally 完成）
            response_received = True
            if chat._di_resp.response is not None:
                # 钩子可能抛出 NoMessageSendError 静默拦截，不发送、不报错
                with contextlib.suppress(NoMessageSendError):
                    await stream_sender.send_final(chat._di_resp.response.content)
            return

        await matcher.send("出错了稍后试试吧（错误已反馈）")
        logger.opt(exception=e, colors=True, raw=True).exception(
            "程序发生了未捕获的异常"
        )
    finally:
        if chat._di_resp.response is not None:
            insights = await InsightsModel.get()
            debug_log(f"获取洞察数据完成，使用计数: {insights.usage_count}")
            assert chat._di_working.context_wrap is not None
            if (usg := chat._di_resp.response.usage) is None:
                resp: str = chat._di_resp.response.content
                usg_prompt: int = 0
                for i in text_generator(
                    chat._di_working.context_wrap.unwrap(), full_message=True
                ):
                    usg_prompt += await asyncio.to_thread(
                        hybrid_token_count, i, tokenizer_type="jieba"
                    )
                usg_gen = await asyncio.to_thread(
                    hybrid_token_count, resp, tokenizer_type="jieba"
                )
                usg = UniResponseUsage(
                    prompt_tokens=usg_prompt,
                    completion_tokens=usg_gen,
                    total_tokens=usg_prompt + usg_gen,
                )

            usage = gather_usage(usg, chat._di_resp.extra_usage)
            add_usage(insights, usage)
            await insights.save()
            debug_log(f"更新全局统计完成，使用计数: {insights.usage_count}")

            ins = await cudr.get_metadata(get_uni_user_id(event))
            for d in (
                (
                    ins,
                    await cudr.get_metadata(f"user_{event.user_id}"),
                )
                if hasattr(event, "group_id")
                else (ins,)
            ):
                d.called_count
                add_usage(d, usage)
                await cudr.update_metadata(d)
