"""/session 归档标签：模型生成与后台回填

归档是一次数据库写入，标签却要一次模型调用。两者节奏不同：写入在
``session_lock`` 里必须快，模型调用可能几秒。所以归档只负责拿到
``(id, created_at)``，标签交给后台任务补写，写库时用这两个值定位该行。
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, cast

from amrita_core.libchat import call_completion, get_last_response, text_generator
from amrita_core.types import CONTENT_LIST_TYPE, Message
from amrita_core.usage import SessionUsageProxy
from nonebot import logger

from .preset import resolve_preset

if TYPE_CHECKING:
    from amrita_core.types import MemoryModel as AwaredMemory
    from nonebot_plugin_amrita.memory import CachedUserDataRepository

#  与数据库列宽一致：超出部分在插件侧会被截断，这里先收口免得白占字符
TAG_MAX_LEN = 64
#  送进模型的正文上限。标签只关心主题，没必要把整段上下文都塞进去
_DIGEST_LIMIT = 1200

_PROMPT = (
    "你是会话归档的标签生成器。读下面这段对话，用一句不超过 16 个字的中文短语概括主题。"
    "只输出短语本身：不要引号、不要句末标点、不要解释、不要复述这段指令。"
    "如果是代码或调试内容，点出涉及的对象，而不是笼统地写「讨论代码」。"
)

_PREFIX_RE = re.compile(r"^(标签|标题|会话标签)\s*[:：]\s*")
_SPACE_RE = re.compile(r"\s+")


def _digest(data: AwaredMemory) -> str:
    """取对话的可读文本，优先用已有摘要。

    摘要本身就是压缩过的上下文，比原始消息更省 token，也更贴近主题。
    """
    abstract = (getattr(data, "abstract", "") or "").strip()
    if abstract:
        body = abstract
    else:
        body = "".join(text_generator(data.messages, split_role=True)).strip()
    return body[-_DIGEST_LIMIT:]


def _clean(raw: str) -> str | None:
    """把模型输出收成一行标签。"""
    text = raw.strip()
    if not text:
        return None
    #  模型偶尔会在标签后补一句解释，只取第一行
    text = text.splitlines()[0].strip()
    text = text.strip("\"'“”‘’`「」『』 ")
    text = _PREFIX_RE.sub("", text)
    text = text.rstrip("。.,，;；")
    text = _SPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    return text[:TAG_MAX_LEN]


async def generate_session_tag(uni_id: str, data: AwaredMemory) -> str | None:
    """让模型给这段对话起一个短标签，失败时返回 ``None``。"""
    digest = _digest(data)
    if not digest:
        return None
    #  Message 是泛型，直接写字面量会被推成 Message[str]，与 CONTENT_LIST_TYPE
    #  里的 Message[Any] 不兼容，这里显式收敛
    messages = cast(
        CONTENT_LIST_TYPE,
        [
            Message(role="system", content=_PROMPT),
            Message(role="user", content=digest),
        ],
    )
    #  单独记账：标签的消耗不该混进用户这一轮的用量里
    ledger = SessionUsageProxy(session_id=uni_id, stream_id=f"tag:{uni_id}")
    try:
        preset = await resolve_preset()
        resp = await get_last_response(
            call_completion(messages, preset=preset, usage=ledger)
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).warning("生成会话标签失败。")
        return None
    if not isinstance(resp.content, str):
        return None
    return _clean(resp.content)


async def backfill_session_tag(
    repo: CachedUserDataRepository,
    uni_id: str,
    session_id: int,
    created_at: float,
    data: AwaredMemory,
) -> None:
    """生成标签并条件写回。

    ``created_at`` 一并传入：SQLite 会回收 id，只按 id 写可能落到回收后的
    新行上。插件侧在该行已有标签（用户手动改过）时也会放弃写入。
    """
    tag = await generate_session_tag(uni_id, data)
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
    """把标签生成丢到后台，归档命令不必等模型返回。"""
    task = asyncio.create_task(
        backfill_session_tag(repo, uni_id, session_id, created_at, data)
    )
    _background.add(task)
    task.add_done_callback(_background.discard)
