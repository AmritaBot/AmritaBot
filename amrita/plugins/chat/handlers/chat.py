"""聊天处理器模块"""

import asyncio
import random
from asyncio import CancelledError
from datetime import datetime

from amrita_core import (
    PresetManager,
    StateContext,
    TextContent,
    UniResponse,
    UniResponseUsage,
    debug_log,
    logger,
)
from amrita_core.base.adapter import COMPLETION_RETURNING
from amrita_core.builtins.agent import (
    HybridReActAgentStrategy,
    NoActionAgentStrategy,
    ReActAgentStrategy,
    gather_usage,
)
from amrita_core.chatmanager import (
    ChatObject as CoreChatObject,
)
from amrita_core.chatmanager.chat_object import DatabackendOptions
from amrita_core.contents import (
    ImageMessage,
    MessageWithMetadata,
    StringMessageContent,
)
from amrita_core.types import USER_INPUT, Content, ImageContent, ImageUrl
from amrita_sense.hook.exception import MatcherException as ChatException
from beartype.typing import Sequence
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageSegment,
)
from nonebot.adapters.onebot.v11.event import (
    GroupMessageEvent,
    MessageEvent,
    Reply,
)
from nonebot.exception import MatcherException, NoneBotException, ProcessException
from nonebot.matcher import Matcher
from pytz import utc

from amrita.plugins.chat.config import ConfigManager, config_manager
from amrita.plugins.chat.runtime import (
    AMRITA_CTX_KEY,
    AmritaBotContext,
    bot_chat_manager,
    get_amrita_ctx,
    pending_chatobj,
)
from amrita.plugins.chat.runtime_session import SessionManager
from amrita.plugins.chat.utils.app import (
    CachedUserDataRepository,
    MemorySchema,
)
from amrita.plugins.chat.utils.functions import (
    get_friend_name,
    split_message_into_chats,
    synthesize_message,
)
from amrita.plugins.chat.utils.libchat import add_usage
from amrita.plugins.chat.utils.lock import get_group_lock, get_private_lock
from amrita.plugins.chat.utils.sql import (
    InsightsModel,
    get_any_id,
    get_uni_user_id,
)
from amrita.utils.admin import send_to_admin

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
        result = (
            f"{content}\n"
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


async def send_response(chat: CoreChatObject, response: str):
    """发送聊天模型的回复，根据配置选择不同的发送方式。"""
    ctx = get_amrita_ctx(chat)
    matcher = ctx["matcher"]
    bot_config = ctx["bot_config"]
    event = ctx["event"]

    chat.last_call = datetime.now(utc)
    debug_log(f"发送响应: {response[:50]}..")  # 只显示前50个字符
    if not bot_config.function.nature_chat_style:
        await matcher.send(
            MessageSegment.reply(event.message_id) + MessageSegment.text(response)
        )
    elif response_list := split_message_into_chats(response):
        for message in response_list:
            await matcher.send(MessageSegment.text(message))
            await asyncio.sleep(
                random.randint(1, 3) + (len(message) // random.randint(80, 100))
            )


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
        formatter = (
            format_msg_xml
            if config_manager.config.function.message_type == "xml"
            else format_msg_legacy
        )
        body = formatter(role, str(user_name), str(user_id), content)
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
      4. chat.begin() → lock → await chat
      5. 后处理：usage 统计、memory 持久化
    """
    if any(
        event.message.extract_plain_text().strip().startswith(prefix)
        for prefix in command_prefix
        if prefix.strip()
    ):
        matcher.skip()
    session_id = get_uni_user_id(event)
    train = (
        config_manager.group_train
        if isinstance(event, GroupMessageEvent)
        else config_manager.private_train
    )
    config = ConfigManager().config
    can_send_message: bool = True
    cudr = CachedUserDataRepository()

    #  阶段 1：加载 memory 与会话管理
    is_group = isinstance(event, GroupMessageEvent)
    any_id, _ = get_any_id(event)
    memory: MemorySchema = await cudr.get_memory(any_id, is_group)
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

    # 构建定制化的 system prompt
    msg_type = config.function.message_type

    if msg_type == "xml":
        format_desc = (
            "你的工作环境是一个社交软件。**输入**的聊天记录使用 XML 标签标记：\n"
            '  <msg role="群主/管理员/普通成员/自己" name="昵称" uid="QQ号">\n'
            "  消息内容（多行）\n"
            "  </msg>\n"
            "引用消息使用 <ref name='...' uid='...'>...</ref> 包裹。\n"
            "你的**输出**必须是纯自然语言文本，**严禁**输出任何 XML 标签、属性或类似的结构化标记。\n"
            "正确示例：\n"
            "  输入：<msg role='普通成员' name='张三' uid='12345'>今天天气真好</msg>\n"
            "  输出：今天天气真好呢。\n"
            "错误示例（**禁止**）：\n"
            "  输入：<msg role='普通成员' name='张三' uid='12345'>今天天气真好</msg>\n"
            "  输出：<msg role='自己' name='爱丽丝' uid='67890'>是啊，阳光明媚。</msg>\n"
        )
    else:
        format_desc = (
            "你的工作环境是一个社交软件。所有**输入**的聊天记录遵循以下格式：\n"
            "- 每条消息以 [身份] 开头，方括号内是消息发送者的身份标记（群主/管理员/普通成员/自己）\n"
            "- 身份后跟 [昵称（QQ号）] 再跟 说:内容\n"
            "  示例: [普通成员][张三（12345）]说:今天天气真好\n"
            "- 用户输入中已对特殊字符做了全角转义（［ ］ 说：），避免与格式标记混淆\n"
            "你的**输出**必须是纯自然语言文本，**严禁**使用上述方括号或“说:”格式，也不能添加任何身份、昵称或QQ号标记。\n"
            "正确示例：\n"
            "  输入：[普通成员][张三（12345）]说:今天天气真好\n"
            "  输出：今天天气真好呢。\n"
            "错误示例（**禁止**）：\n"
            "  输入：[普通成员][张三（12345）]说:今天天气真好\n"
            "  输出：[自己][爱丽丝（67890）]说:是啊，阳光明媚。\n"
        )
    train_content = (
        "<SCHEMA_EXTENSIONS>\n"
        + "你在纯文本环境工作，不允许使用MarkDown回复。"
        + f"<IO_REQUIREMENT>\n{format_desc}\n</IO_REQUIREMENT>"
        + "请以你自己的角色身份参与讨论，交流时不同话题尽量不使用相似句式回复。"
        + "`<EXTRA>`规则仅作为补充，如果与EXTRA规则上文有冲突，请遵循上文规则。"
        + "\n</SCHEMA_EXTENSION>\n"
        + (
            train["content"]
            .replace("{self_id}", str(event.self_id))
            .replace("{user_id}", str(event.user_id))
            .replace("{user_name}", str(event.sender.nickname))
        )
        + (
            f"<EXTRA>\n（此处是EXTRA规则，如果与上文有任何冲突，请忽略此EXTRA规则）\n{memory.extra_prompt}\n</EXTRA>"
            if config.function.allow_custom_prompt
            else ""
        )
    )
    train_dict = {"role": "system", "content": train_content}

    #  阶段 4：创建 ChatObject
    ctx: AmritaBotContext = {
        "matcher": matcher,
        "bot": bot,
        "event": event,
        "bot_config": ConfigManager().config,
    }
    core_ctx = StateContext(session_id, memory=memory.memory_json)
    chat: CoreChatObject = CoreChatObject(
        train=train_dict,
        user_input=content,
        context=core_ctx,
        session_id=None,
        preset=await ConfigManager().get_preset(config.preset),
        hook_args=(event, matcher, bot),
        hook_kwargs={AMRITA_CTX_KEY: ctx},
        exception_ignored=(ProcessException, MatcherException),
        agent_strategy=strategy,
        chat_man=bot_chat_manager,
        backend_options=DatabackendOptions(
            skip_memory_fetch=True,
            skip_memory_commit=True,
            skip_mcp_fetch=True,
            skip_tools_fetch=True,
            skip_presets_fetch=True,
        ),
    )

    #  阶段 5：设置回调并启动
    async def on_stream_message(message: COMPLETION_RETURNING):
        nonlocal can_send_message
        if isinstance(message, str):
            return
        elif isinstance(message, MessageWithMetadata):
            match message.metadata.get("type", ""):
                case "system":
                    await matcher.send(message.content)
                case "reasoning":
                    if not config.core.builtin.agent_reasoning_hide:
                        await matcher.send(message.content)
                case "tool_prediction":
                    if config.core.builtin.agent_tool_call_notice == "notify":
                        await matcher.send("⏩ 已决定工具调用")
                case "function_call":
                    if (
                        message.metadata["is_done"]  # type: ignore[typeddict-unknown-key]
                        and config.core.builtin.agent_tool_call_notice == "notify"
                    ):
                        function_name = message.metadata["function_name"]  # type: ignore[typeddict-unknown-key]
                        if (err := message.metadata.get("err")) is not None:
                            logger.opt(exception=err, colors=True).exception(
                                f"Tool {function_name} execution failed: {err}"
                            )
                            await matcher.send(
                                f"ERR: {function_name} 执行失败",
                            )
                        else:
                            await matcher.send(f"调用了工具：{function_name}")
                case "text":
                    if (
                        message.metadata["extra_type"] == "structured_reasoning_step"
                        and not config.core.builtin.agent_reasoning_hide
                    ):
                        await matcher.send(message.content)
                case "error":
                    if message.metadata.get("extra_type") == "cookie":
                        can_send_message = False
                        await send_to_admin(
                            f"安全警告：用户请求导致了可能的Prompt泄露。已在response检测到cookie泄露，请检查！\n用户请求：\n{chat.user_input!s}\n模型模型输出：\n{chat.response.content!s}"
                        )
                        return await matcher.send(random.choice(config.llm.block_msg))
                    error = message.metadata["error"]  # type: ignore[typeddict-unknown-key]
                    logger.opt(exception=error, colors=True).exception(
                        f"有错误发生:{error}"
                    )
        elif isinstance(message, StringMessageContent):
            await matcher.send(message.get_content())
        elif isinstance(message, ImageMessage):
            msg = MessageSegment.image(await message.get_image())
            await matcher.send(msg)

    chat.io_stream.set_callback_func(on_stream_message)

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

    try:
        pending_chatobj[session_id].append(chat)
        try:
            async with lock:
                pending_chatobj[session_id].remove(chat)
                debug_log("继续运行...")

                await chat.begin()
                memory.memory_json = chat.data
                await cudr.update_memory_data(memory)
                if can_send_message:
                    await send_response(chat, chat.response.content)
        finally:
            # 兜底：异常时清理 pending
            if chat in pending_chatobj[session_id]:
                pending_chatobj[session_id].remove(chat)

    except BaseException as e:
        if isinstance(e, (NoneBotException, ChatException)):
            raise

        if isinstance(e, CancelledError):
            return
        await matcher.send("出错了稍后试试吧（错误已反馈）")
        logger.opt(exception=e, colors=True).exception("程序发生了未捕获的异常")
    finally:
        response: UniResponse[str, None] | None
        if (response := getattr(chat, "response", None)) is not None:
            insights = await InsightsModel.get()
            debug_log(f"获取洞察数据完成，使用计数: {insights.usage_count}")
            usg = response.usage or UniResponseUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            )
            usage = gather_usage(usg, chat.extra_usage)
            add_usage(insights, usage)
            await insights.save()
            debug_log(f"更新全局统计完成，使用计数: {insights.usage_count}")

            ins = await cudr.get_metadata(*get_any_id(event))
            for d in (
                (
                    ins,
                    await cudr.get_metadata(event.user_id, False),
                )
                if hasattr(event, "group_id")
                else (ins,)
            ):
                d.called_count
                add_usage(d, usage)
                await cudr.update_metadata(d)
