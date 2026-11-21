"""/思考块摘要：独立于主对话的一次调用，把长思考压成可直接展示的一段话。"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, cast

from amrita_core.config import get_config
from amrita_core.libchat import call_completion, get_last_response
from amrita_core.types import CONTENT_LIST_TYPE, Message
from amrita_core.types.preset import ThinkingConfig, resolve_max_output
from nonebot import logger

from .preset import resolve_preset

if TYPE_CHECKING:
    from amrita_core.usage import SessionUsageProxy

#  送进模型的原始思考上限：摘要只需要知道想了什么，不需要逐字复读
_DIGEST_LIMIT = 6000
#  摘要正文上限，超出按分句截断
SUMMARY_MAX_CHARS = 160
#  思考短于这个长度就没有摘要价值，直接原样返回
_SHORT_CIRCUIT = 120
#  思考 token 与正文共用预算，显式关思考并给输出兜下限，避免正文为空
_SUMMARY_MAX_OUTPUT = 1024
_SUMMARY_TIMEOUT = 20.0

_PROMPT = (
    "你是思考过程的摘要器。用户会给你一段模型的原始思考（可能中英混杂、反复试探、自我纠正），"
    "请把它压成一段简洁的中文摘要。硬性要求：\n"
    "1. 只输出摘要正文，不要标题、不要 Markdown 标记、不要「摘要：」之类的前缀；\n"
    "2. 保留三样东西：最终结论、做过的关键判断及理由、仍未解决或存疑的点；\n"
    "3. 删掉重复的试错、语气词、对指令本身的复述；\n"
    "4. 不超过 120 个汉字，写成 2 到 4 句连贯的话，不要分点；\n"
    "5. 不要评价这段思考好不好，只转述内容。\n"
    "参考下面的示例，注意它们都只保留结论与关键判断。"
)

#  原始思考 -> 摘要，示例刻意保留「乱」与「收」的对比
_FEWSHOTS: list[tuple[str, str]] = [
    (
        "先看报错…KeyError: 'tag'。是不是模型里没这个字段？不对，模型里有，"
        "那应该是数据库没这列。查一下迁移，确实有个 add_column 的迁移。"
        "那为什么启动还报？可能是版本被 stamp 了但 DDL 没跑。先手工补列验证，"
        "补完能起来了，说明猜想成立。要不要顺手修迁移？这个先记着，"
        "本次只处理启动问题。",
        "确认启动失败是因为迁移版本已记录但建列语句未执行，手工补列后启动恢复；"
        "迁移本身的修复留作后续单独处理。",
    ),
    (
        "User asks why the bot replies twice. Let me think: maybe the hook fires twice, "
        "or the matcher sends both final and streamed text. Check send_final: it flushes "
        "reasoning then sends content. Stream path sends chunks... Ah, the reasoning "
        "collector flushes on extra_type change, so it sends many messages, but that's "
        "thinking not the answer. Hmm, maybe the answer is sent by both send_final and "
        "the callback. Need to verify with a log.",
        "怀疑重复回复来自最终响应与流式回调各发了一次，也可能与思考收集器的分段有关；"
        "结论尚未确认，需要用日志验证两条发送路径。",
    ),
    (
        "这个方案要评估两点：成本和延迟。成本上每次请求多一次调用，按 qps 估大概涨一成；"
        "延迟上摘要要等整段思考结束，首字会晚 1 到 2 秒。所以只能在用户主动开启时用，"
        "默认不能开。另外失败要有兜底，退回原文。",
        "该方案每次多一次调用、首字延迟约 1 到 2 秒，因此只适合主动开启；"
        "摘要失败时应回退到原始思考。",
    ),
]

_PREFIX_RE = re.compile(r"^(摘要|思考摘要|总结)\s*[:：]\s*")
_BLANK_RE = re.compile(r"\n{2,}")


def _clean(raw: str) -> str | None:
    """收成一段可发送的摘要，去掉前缀与多余空行。"""
    text = raw.strip()
    if not text:
        return None
    text = _PREFIX_RE.sub("", text)
    text = _BLANK_RE.sub("\n", text).strip()
    if len(text) > SUMMARY_MAX_CHARS:
        #  模型偶尔会写超，优先保留前几句，再兜底硬截断
        cut = text[:SUMMARY_MAX_CHARS]
        for sep in ("。", "；", "\n"):
            if sep in cut:
                cut = cut[: cut.rindex(sep) + 1]
                break
        text = cut.strip()
    return text or None


async def summarize_reasoning(
    raw: str,
    usage: "SessionUsageProxy | None" = None,
) -> str | None:
    """把一段原始思考压成摘要，失败或超时返回 ``None``。

    Args:
        raw: 收集到的完整思考文本
        usage: 传入时把这次调用的用量记进去
    """
    digest = raw.strip()
    if not digest:
        return None
    if len(digest) <= _SHORT_CIRCUIT:
        return digest

    messages: list[Message] = [
        Message(role="system", content=_PROMPT),
    ]
    for src, dst in _FEWSHOTS:
        messages.append(Message(role="user", content=src))
        messages.append(Message(role="assistant", content=dst))
    messages.append(Message(role="user", content=digest[-_DIGEST_LIMIT:]))

    try:
        preset = await resolve_preset()
        #  摘要不需要思考：开思考会先吃掉预算，正文可能一个字都出不来
        preset = preset.model_copy(
            update={
                "thinking_config": ThinkingConfig(
                    thinking_type="disabled",
                    enable_thinking=False,
                    thinking_effort=None,
                )
            }
        )
        budget = max(resolve_max_output(preset, get_config()), _SUMMARY_MAX_OUTPUT)
        preset = preset.model_copy(update={"max_output": budget})
        resp = await asyncio.wait_for(
            get_last_response(
                call_completion(
                    cast(CONTENT_LIST_TYPE, messages), preset=preset, usage=usage
                )
            ),
            timeout=_SUMMARY_TIMEOUT,
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).warning("生成思考摘要失败。")
        return None

    if not isinstance(resp.content, str) or not resp.content.strip():
        logger.warning("思考摘要为空：可能未产出正文，本次回退原始思考。")
        return None
    return _clean(resp.content)
