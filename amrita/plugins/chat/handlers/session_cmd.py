"""/session 域命令：会话管理、元信息、压缩、记忆（合并原 sessions/session/compact/del_memory/abstract）"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING

from amrita_core.components.compaction import ContextCompactor
from amrita_core.types import MemoryModel as AwaredMemory
from amrita_core.types import UniResponseUsage
from amrita_core.types.preset import resolve_max_context, resolve_max_output
from amrita_core.usage import SessionUsageProxy
from amrita_sense.hook.matcher import MatcherFactory
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot_plugin_amrita.database import UserDataExecutor
from nonebot_plugin_amrita.memory import CachedUserDataRepository
from nonebot_plugin_orm import get_session

from amrita.plugins.chat.utils.libchat import add_usage

from ..check_rule import is_group_admin_if_is_in_group
from ..config import config_manager
from ..events import SessionCompactEvent
from ..utils.context_store import fold_media_in_messages
from ..utils.data_access import update_memory
from ..utils.preset import resolve_preset
from ..utils.session_guard import active_chat_object, is_session_busy, session_lock
from ..utils.sql import get_uni_user_id

if TYPE_CHECKING:
    from amrita_core.chatmanager import ChatObject as CoreChatObject

# 上下文占用低于 MaxTokens 该比例时拒绝压缩
COMPACT_MIN_RATIO = 0.15


def _live_memory(chat: CoreChatObject) -> AwaredMemory | None:
    """取运行中对象的活记忆；DI 上下文未就绪（``LOAD_STATE`` 之前）时返回 ``None``。"""
    try:
        return chat.data
    except RuntimeError:
        return None


def _live_usage(chat: CoreChatObject) -> UniResponseUsage[int] | None:
    """运行中会话的当前用量。

    颗粒度是 per-req：返回的是**最新一次** provider 请求的上下文规模，
    不是本轮多步调用的累加（累加在 ``memory.billing`` 里）。

    优先取账本最新一条：provider 一上报就入账，比 ``memory.usage`` 更早可见。
    账本为空（本轮尚未发起请求）时回落到 ``memory.usage``，即上一轮的规模。
    """
    proxy = chat._di_resp.usage
    if proxy is not None and proxy.records:
        last = proxy.records[-1]
        return UniResponseUsage(
            prompt_tokens=last.prompt_tokens,
            completion_tokens=last.completion_tokens,
            total_tokens=last.total_tokens,
            cache_hit=last.cache_hit,
            cache_creation=last.cache_creation,
        )
    live = _live_memory(chat)
    return live.usage if live is not None else None


# 会话管理


async def _session_list(event: MessageEvent, matcher: Matcher) -> None:
    """显示历史会话列表"""
    repo = CachedUserDataRepository()
    sessions = await repo.get_sesssions(get_uni_user_id(event))
    if not sessions:
        await matcher.finish("没有历史会话")
    msg = "历史会话\n"
    for index, s in enumerate(sessions):
        if s.data.messages:
            abstract = s.data.abstract[:15] or "（无描述）"
            t = datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d %I:%M:%S %p")
            msg += f"编号：{index}）{abstract}... 时间：{t}\n"
    await matcher.finish(msg)


async def _session_use(event: MessageEvent, matcher: Matcher, index: str) -> None:
    """将当前会话覆盖为指定编号的会话"""
    repo = CachedUserDataRepository()
    try:
        session_index = int(index)
        user_sessions = await repo.get_sesssions(get_uni_user_id(event))
    except ValueError:
        await matcher.finish("请输入正确的编号")
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception("覆盖记忆文件失败。")
        await matcher.finish("覆盖记忆文件失败，这个对话可能损坏了。")
    if not 0 <= session_index < len(user_sessions):
        await matcher.finish("请输入正确的编号")
    target = user_sessions[session_index]
    try:
        memory_data = await repo.get_memory(get_uni_user_id(event))
        memory_data.memory_json.messages = deepcopy(target.data.messages)
        await update_memory(memory_data)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception("覆盖记忆文件失败。")
        await matcher.finish("覆盖记忆文件失败，这个对话可能损坏了。")
    await matcher.send("✅ 已完成记忆覆盖。")


async def _session_del(event: MessageEvent, matcher: Matcher, index: str) -> None:
    """删除指定编号的会话"""
    repo = CachedUserDataRepository()
    uni_id = get_uni_user_id(event)
    try:
        session_index = int(index)
        user_sessions = await repo.get_sesssions(uni_id)
    except ValueError:
        await matcher.finish("请输入正确的编号")
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception(
            "删除指定编号会话失败。"
        )
        await matcher.finish("删除指定编号会话失败。")
    if not 0 <= session_index < len(user_sessions):
        await matcher.finish("请输入正确的编号")
    removed = list(user_sessions).pop(session_index)
    try:
        async with get_session() as session:
            async with UserDataExecutor(uni_id, session) as executor:
                await executor.remove_session(removed.id)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception(
            "删除指定编号会话失败。"
        )
        await matcher.finish("删除指定编号会话失败。")
    await matcher.send("✅ 已删除对应的会话。")


async def _session_archive(event: MessageEvent, matcher: Matcher) -> None:
    """归档当前会话"""
    repo = CachedUserDataRepository()
    uni_id = get_uni_user_id(event)
    try:
        memory_data = await repo.get_memory(uni_id)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception("归档当前会话失败。")
        await matcher.finish("归档当前会话失败。")
    if not memory_data.memory_json.messages:
        await matcher.finish("当前对话为空！")
    #  归档副本同样不能带图片内容：先折叠再深拷贝
    fold_media_in_messages(memory_data.memory_json.messages)
    new_session = AwaredMemory(
        messages=deepcopy(memory_data.memory_json.messages),
        abstract=memory_data.memory_json.abstract,
    )
    try:
        async with get_session() as session:
            async with UserDataExecutor(uni_id, session) as executor:
                await executor.add_session(new_session)
        memory_data.memory_json.messages = []
        await update_memory(memory_data)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception("归档当前会话失败。")
        await matcher.finish("归档当前会话失败。")
    await matcher.finish("✅ 当前会话已归档。")


async def _session_clear(event: MessageEvent, matcher: Matcher) -> None:
    """清空所有历史会话"""
    repo = CachedUserDataRepository()
    uni_id = get_uni_user_id(event)
    user_sessions = await repo.get_sesssions(uni_id)
    if user_sessions:
        async with get_session() as session:
            async with UserDataExecutor(uni_id, session) as executor:
                await executor.remove_session(*[s.id for s in user_sessions])
    await matcher.finish("✅ 会话已清空。")


# 元信息

#  上下文占用条：已用 / 响应预留 / 未用
_BAR_WIDTH = 20
_BAR_USED = "🟩"
_BAR_RESERVED = "🟨"
_BAR_FREE = "⬜"


def _render_context_bar(used: int, reserved: int, window: int) -> str:
    """把上下文占用渲染成方块条形图。

    Args:
        used: 已用 prompt tokens；provider 未上报时传 0
        reserved: 为响应输出预留的 tokens
        window: 注意力窗口（``resolve_max_context``）

    Returns:
        由 🟩 / 🟨 / ⬜ 组成的定宽条形图；窗口非法时全为未用
    """
    if window <= 0:
        return _BAR_FREE * _BAR_WIDTH
    used_blocks = min(_BAR_WIDTH, round(used / window * _BAR_WIDTH))
    reserved_blocks = min(
        _BAR_WIDTH - used_blocks, round(reserved / window * _BAR_WIDTH)
    )
    free_blocks = max(0, _BAR_WIDTH - used_blocks - reserved_blocks)
    return (
        _BAR_USED * used_blocks
        + _BAR_RESERVED * reserved_blocks
        + _BAR_FREE * free_blocks
    )


async def _session_info(event: MessageEvent, matcher: Matcher) -> None:
    """展示当前会话的模型、思考深度与上下文占用

    运行中的会话从活 ``ChatObject`` 取上下文规模与消息数：``repo`` 缓存的
    ``memory_json`` 要等 ``COMMIT_MEMORY`` 才更新，运行中读它拿到的是上一轮的值。
    会话空闲时才查库。
    """
    config = config_manager.config
    uni_id = get_uni_user_id(event)

    chat = active_chat_object(uni_id)
    live_memory = _live_memory(chat) if chat is not None else None
    if live_memory is not None:
        data = live_memory
    else:
        data = (await CachedUserDataRepository().get_memory(uni_id)).memory_json

    preset = await resolve_preset()
    window = resolve_max_context(preset, config.core)
    reserved = resolve_max_output(preset, config.core)
    #  usage 是 per-req：provider 上报的最新一次请求的上下文规模
    usage = data.usage
    if chat is not None:
        live = _live_usage(chat)
        if live is not None:
            usage = live
    used = usage.prompt_tokens if usage is not None else 0
    free = max(0, window - used - reserved)
    ratio = config.core.llm.compaction_trigger_ratio

    lines = ["📊 当前会话元信息"]
    lines.append(f"模型：{preset.name}（{preset.model}）")
    if preset.thinking_config is not None:
        tc = preset.thinking_config
        enabled = tc.thinking_type == "enabled" or tc.enable_thinking is True
        state = "已启用" if enabled else "已关闭"
        lines.append(f"思考深度：{tc.thinking_effort or '—'}（{state}）")
    lines.append(_render_context_bar(used, reserved, window))
    if usage is None:
        lines.append("  已用   尚无数据（本轮尚未发起请求）")
    elif window > 0:
        lines.append(f"  已用   {used:,} / {window:,}（{used / window:.1%}）")
    else:
        lines.append(f"  已用   {used:,}")
    lines.append(f"  预留   {reserved:,}（响应输出）")
    lines.append(f"  未用   {free:,}")
    threshold = int(window * ratio)
    lines.append(f"  压缩线 {threshold:,}（触发比例 {ratio:.0%}）")
    if window > 0 and used >= threshold:
        lines.append("  ⚠️ 已超过压缩线，下次请求前将自动压缩上下文")
    roles = Counter(getattr(msg, "role", "?") for msg in data.messages)
    detail = " ".join(f"{role}:{count}" for role, count in roles.items())
    lines.append(f"消息数：{len(data.messages)} 条（{detail or '空'}）")
    if live_memory is not None:
        lines.append("（数据来自本轮运行中的会话）")
    await matcher.send("\n".join(lines))


# 压缩


async def _session_compact(event: MessageEvent, matcher: Matcher, force: bool) -> None:
    """压缩当前会话上下文：将早期消息总结为摘要

    调用方已持有 ``session_lock``，本函数内的改内存与写库都在该锁内完成，
    因此不会与本轮对话结束时的 ``commit_memory`` 竞争。

    ``repo.make_lock`` 只用于在耗时的摘要调用期间占住数据库行，
    防止其他数据库侧写入者读到半压缩状态；它**不是**与 chat 路径互斥的锁。
    ``update_memory`` 不能嵌进这个 ``with``：其内部会再次获取同一把
    ``aiologic.Lock``，而该锁不可重入，嵌套会直接抛 ``RuntimeError``。
    """
    config = config_manager.config
    repo = CachedUserDataRepository()
    uni_id = get_uni_user_id(event)
    memory = await repo.get_memory(uni_id)
    data = memory.memory_json
    if not data.messages:
        await matcher.finish("当前会话为空，无需压缩。")

    preset = await resolve_preset()
    budget = resolve_max_context(preset, config.core)
    current_tokens = data.usage.prompt_tokens if data.usage is not None else 0

    ratio = current_tokens / budget if budget > 0 else 1.0
    if not force and ratio < COMPACT_MIN_RATIO:
        await matcher.finish(
            f"当前上下文 {current_tokens}/{budget} tokens（{ratio:.1%}），"
            f"未达到 {COMPACT_MIN_RATIO:.0%} 的压缩阈值，暂不需要压缩。"
        )

    #  摘要调用单独记账；compact() 成功后清空 usage，故占用与消息数需提前留存
    ledger = SessionUsageProxy(session_id=uni_id, stream_id=f"compact:{uni_id}")
    compactor = ContextCompactor(config=config.core, preset=preset, usage=ledger)
    before_count = len(data.messages)
    try:
        async with repo.make_lock(uni_id):
            compacted = await compactor.compact(data)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception("压缩会话上下文失败。")
        await matcher.finish("压缩失败，会话已回滚。")

    await update_memory(memory)

    usage = ledger.extra_total
    if usage.prompt_tokens or usage.completion_tokens:
        ins = await repo.get_metadata(uni_id)
        add_usage(ins, usage)
        await repo.update_metadata(ins)

    if not compacted:
        await matcher.finish(
            f"当前上下文 {current_tokens}/{budget} tokens，没有可折叠的历史，无需压缩。"
        )

    folded = before_count - len(data.messages)
    msg = (
        f"✅ 压缩完成：折叠 {folded} 条历史消息"
        f"（压缩前占用 {current_tokens}/{budget} tokens）"
    )
    if usage.prompt_tokens or usage.completion_tokens:
        msg += f"（摘要消耗 {usage.prompt_tokens + usage.completion_tokens} tokens）"

    #  扩展点：压缩完成后的钩子（消息条数、占用与摘要用量均已确定）
    await MatcherFactory.trigger_event(
        SessionCompactEvent(
            event=event,
            matcher=matcher,
            session_id=uni_id,
            before_count=before_count,
            after_count=len(data.messages),
            before_tokens=current_tokens,
            budget=budget,
            summary_usage=usage,
        )
    )
    await matcher.send(msg)


# 记忆


async def _session_forget(event: MessageEvent, matcher: Matcher) -> None:
    """清空当前记忆"""
    repo = CachedUserDataRepository()
    data = await repo.get_memory(get_uni_user_id(event))
    data.memory_json.messages.clear()
    await update_memory(data)
    await matcher.send("上下文已清除")


async def _session_abstract(event: MessageEvent, matcher: Matcher, clear: bool) -> None:
    """查看或清空当前会话摘要"""
    repo = CachedUserDataRepository()
    data = await repo.get_memory(get_uni_user_id(event))
    if clear:
        data.memory_json.abstract = ""
        await update_memory(data)
        await matcher.send("已清空对话上下文摘要")
    else:
        await matcher.send(
            f"当前对话上下文摘要：\n{str(data.memory_json.abstract) or '无'}"
        )
    data.clean()  # Ensure the memory is not dirty


# 入口

#  破坏性指令会与运行中的对话抢同一份记忆，详见 utils/session_guard.py
_DESTRUCTIVE_SUBS = frozenset(
    {
        "use",
        "set",
        "覆盖",
        "恢复",
        "del",
        "delete",
        "删除",
        "archive",
        "归档",
        "forget",
        "失忆",
        "清除记忆",
        "compact",
        "压缩",
        "clear",
        "清空",
    }
)

_FORCE_FLAGS = frozenset({"force", "-f", "--force"})

#  abstract 的查看是只读的，只有带这些参数时才会写库
_ABSTRACT_SUBS = frozenset({"abstract", "摘要"})
_ABSTRACT_CLEAR_FLAGS = frozenset({"clear", "clean", "reset"})

_HELP_TEXT = (
    "用法：\n"
    "/session info — 会话元信息（模型/思考/上下文占用）\n"
    "/session list — 历史会话\n"
    "/session use <编号> — 恢复指定会话\n"
    "/session del <编号> — 删除指定会话\n"
    "/session archive — 归档当前会话\n"
    "/session clear — 删除全部历史会话（需二次确认）\n"
    "/session clear confirm — 确认删除全部历史会话\n"
    "/session compact [force] — 压缩上下文\n"
    "/session forget — 清除当前对话上下文（不影响历史归档）\n"
    "/session abstract [clear] — 查看/清空摘要\n"
    "会修改记忆的指令（含 clear 类的 abstract）在会话运行中会被拒绝，追加 force 可等待本轮结束后执行。"
)


def _sub_arg(arg_list: list[str]) -> str:
    """取子命令之后的第一个非 force 参数（无则为空串）"""
    return next((a for a in arg_list[1:] if a not in _FORCE_FLAGS), "")


def _is_destructive(sub: str, arg_list: list[str]) -> bool:
    """该子命令本次调用是否会修改记忆。

    ``abstract`` 是条件破坏性的：查看摘要只读，带 ``clear`` 类参数才写库。
    因此不能整体放进 ``_DESTRUCTIVE_SUBS`` —— 那会让运行中的会话连查看摘要
    都被拒绝；但 ``abstract clear`` 必须和其余破坏性指令一样持锁，
    否则清空摘要会被本轮结束时的记忆回写静默撤销。
    """
    if sub in _DESTRUCTIVE_SUBS:
        return True
    return sub in _ABSTRACT_SUBS and _sub_arg(arg_list) in _ABSTRACT_CLEAR_FLAGS


async def _dispatch_subcommand(
    sub: str,
    arg_list: list[str],
    force: bool,
    event: MessageEvent,
    matcher: Matcher,
) -> None:
    """按子命令分发（``force`` 对 compact 另有跳过阈值检查的含义）"""
    rest = _sub_arg(arg_list)
    match sub:
        case "info" | "信息" | "元信息":
            await _session_info(event, matcher)
        case "list" | "历史" | "列表":
            await _session_list(event, matcher)
        case "use" | "set" | "覆盖" | "恢复":
            await _session_use(event, matcher, rest)
        case "del" | "delete" | "删除":
            await _session_del(event, matcher, rest)
        case "archive" | "归档":
            await _session_archive(event, matcher)
        case "clear" | "清空":
            if rest not in ("confirm", "确认"):
                await matcher.finish(
                    "⚠️ /session clear 会删除全部历史会话，不可恢复。\n"
                    "   如果你只是想清空当前对话上下文，请用 /session forget。\n\n"
                    "确认请发送：/session clear confirm"
                )
            await _session_clear(event, matcher)
        case "compact" | "压缩":
            await _session_compact(event, matcher, force)
        case "forget" | "失忆" | "清除记忆":
            await _session_forget(event, matcher)
        case "abstract" | "摘要":
            clear = rest in _ABSTRACT_CLEAR_FLAGS
            await _session_abstract(event, matcher, clear)
        case _:
            await matcher.finish(_HELP_TEXT)


async def session(
    bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    """/session 命令入口"""
    if not await is_group_admin_if_is_in_group(event, bot):
        await matcher.finish("你没有权限执行此命令。")

    arg_list = args.extract_plain_text().strip().split()
    sub = arg_list[0] if arg_list else "info"
    force = any(a in _FORCE_FLAGS for a in arg_list[1:])

    if _is_destructive(sub, arg_list):
        if is_session_busy(get_uni_user_id(event)) and not force:
            await matcher.finish(
                "⚠️ 当前会话正在运行中，该指令的结果会被本轮结束时的记忆回写覆盖。\n"
                f"   请等待回复完成，或追加 force 等待本轮结束后执行："
                f"/session {sub} force"
            )
        #  空闲路径同样必须持锁：否则「检查通过」到「执行」之间可以插入新一轮对话，本轮结束时的记忆回写会覆盖指令刚做的修改
        async with session_lock(event):
            await _dispatch_subcommand(sub, arg_list, force, event, matcher)
        return

    await _dispatch_subcommand(sub, arg_list, force, event, matcher)
