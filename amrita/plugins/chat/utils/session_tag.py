"""/session 归档标签的生成与回填

标签要一次模型调用，归档写入却在 ``session_lock`` 内必须快，所以归档只取
``(id, created_at)``，标签交给后台任务补写。
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, cast

from amrita_core.libchat import call_completion, get_last_response, text_generator
from amrita_core.types import CONTENT_LIST_TYPE, Message
from amrita_core.usage import SessionUsageProxy
from nonebot import logger

from .libchat import add_usage
from .preset import resolve_preset

if TYPE_CHECKING:
    from amrita_core.types import MemoryModel as AwaredMemory
    from nonebot_plugin_amrita.memory import CachedUserDataRepository

TAG_MAX_LEN = 64
#  一次标签调用的上限，provider 挂起时不能让任务永远挂在 _background 里
TAG_TIMEOUT = 30.0
#  送进模型的正文上限，标签只关心主题
_DIGEST_LIMIT = 1200

_PROMPT = (
    "你是会话归档的标签生成器。读下面这段对话，用一句不超过 16 个字的中文短语概括主题。"
    "只输出短语本身：不要引号、不要句末标点、不要解释、不要复述这段指令。"
    "如果是代码或调试内容，点出涉及的对象，而不是笼统地写「讨论代码」。"
)

_PREFIX_RE = re.compile(r"^(标签|标题|会话标签)\s*[:：]\s*")
_SPACE_RE = re.compile(r"\s+")


def _digest(data: AwaredMemory) -> str:
    """取对话文本，优先用摘要，省 token 也更贴近主题。"""
    abstract = (getattr(data, "abstract", "") or "").strip()
    if abstract:
        body = abstract
    else:
        body = "".join(text_generator(data.messages, split_role=True)).strip()
    return body[-_DIGEST_LIMIT:]


def _clean(raw: str) -> str | None:
    """收成一行标签，并抹掉会破坏 OneBot 消息的字符。"""
    text = raw.strip()
    if not text:
        return None
    #  模型偶尔会在标签后补一句解释，只取第一行
    text = text.splitlines()[0].strip()
    text = text.strip("\"'“”‘’`「」『』 ")
    text = _PREFIX_RE.sub("", text)
    text = text.rstrip("。.,，;；")
    text = _SPACE_RE.sub(" ", text).strip()
    #  方括号与 @ 会拼出 CQ 码，或被解析成提及；展示层还会再转一次文本段
    text = text.replace("[", "【").replace("]", "】").replace("@", "＠")
    if not text:
        return None
    return text[:TAG_MAX_LEN]


async def generate_session_tag(
    uni_id: str,
    data: AwaredMemory,
    ledger: SessionUsageProxy | None = None,
) -> str | None:
    """生成短标签，失败或超时返回 ``None``。

    Args:
        uni_id: 统一用户 ID，用于记账流的标识
        data: 归档快照，读摘要或尾部对话
        ledger: 传入时把这次调用的用量记进去
    """
    digest = _digest(data)
    if not digest:
        return None
    #  Message 是泛型，字面量会被推成 Message[str]，与 CONTENT_LIST_TYPE 不兼容
    messages = cast(
        CONTENT_LIST_TYPE,
        [
            Message(role="system", content=_PROMPT),
            Message(role="user", content=digest),
        ],
    )
    try:
        preset = await resolve_preset()
        resp = await asyncio.wait_for(
            get_last_response(call_completion(messages, preset=preset, usage=ledger)),
            timeout=TAG_TIMEOUT,
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).warning("生成会话标签失败。")
        return None
    if not isinstance(resp.content, str):
        return None
    return _clean(resp.content)


async def _record_usage(
    repo: CachedUserDataRepository, uni_id: str, ledger: SessionUsageProxy
) -> None:
    """把标签调用的 token 记进用户统计，失败不影响标签本身。"""
    usage = ledger.extra_total
    if not (usage.prompt_tokens or usage.completion_tokens):
        return
    try:
        ins = await repo.get_metadata(uni_id)
        add_usage(ins, usage)
        await repo.update_metadata(ins)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).warning("记录标签用量失败。")


async def backfill_session_tag(
    repo: CachedUserDataRepository,
    uni_id: str,
    session_id: int,
    created_at: float,
    data: AwaredMemory,
) -> None:
    """生成并条件写回标签。

    Args:
        repo: 用户数据仓库，走它的锁与写入路径
        uni_id: 统一用户 ID
        session_id: ``add_session`` 返回的归档 id
        created_at: 同次归档的时间戳，用于防止 id 回收后写错行
        data: 归档快照
    """
    ledger = SessionUsageProxy(session_id=uni_id, stream_id=f"tag:{uni_id}")
    tag = await generate_session_tag(uni_id, data, ledger)
    await _record_usage(repo, uni_id, ledger)
    if tag is None:
        return
    try:
        await repo.update_session_tag(uni_id, session_id, tag, created_at)
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).warning("回填会话标签失败。")


#  持引用防止任务被 GC 提前回收
_background: set[asyncio.Task[None]] = set()


def spawn_tag_backfill(
    repo: CachedUserDataRepository,
    uni_id: str,
    session_id: int,
    created_at: float,
    data: AwaredMemory,
) -> None:
    """在后台跑一次标签回填，调用方不等待结果。"""
    task = asyncio.create_task(
        backfill_session_tag(repo, uni_id, session_id, created_at, data)
    )
    _background.add(task)
    task.add_done_callback(_background.discard)
