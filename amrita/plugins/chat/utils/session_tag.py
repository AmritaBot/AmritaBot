"""/session 归档标签的生成与回填

标签要一次模型调用，归档写入却在 ``session_lock`` 内必须快，所以归档只取
``(id, created_at)``，标签交给后台任务补写。
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, cast

from amrita_core.config import get_config
from amrita_core.libchat import call_completion, get_last_response, text_generator
from amrita_core.types import CONTENT_LIST_TYPE, Message, ThinkingConfig
from amrita_core.types.preset import resolve_max_output
from amrita_core.usage import SessionUsageProxy
from nonebot import logger

from .libchat import add_usage
from .preset import resolve_preset

if TYPE_CHECKING:
    from amrita_core.types import MemoryModel as AwaredMemory
    from nonebot_plugin_amrita.memory import CachedUserDataRepository

TAG_MAX_LEN = 64
TAG_GENERATE_MAX_LEN = 24
#  思考模型会先花掉 reasoning tokens，预算太小会让正文一个字都出不来
TAG_MAX_OUTPUT = 2048
#  一次标签调用的上限，provider 挂起时不能让任务永远挂在 _background 里
TAG_TIMEOUT = 30.0
#  送进模型的正文上限，标签只关心主题
_DIGEST_LIMIT = 1200

_PROMPT = """你是会话归档的「命名员」，任务只有一个：给这段对话起一个短名字。

这不是摘要，也不是上下文压缩。不要保留信息、不要分点、不要标题、不要复述内容，
读的人只看这一行字判断「这条会话是聊什么的」。写多了就是错。

硬性要求：
1. 输出一句中文短语，不超过 16 个汉字，不带标点结尾。
2. 不要 Markdown：不要 #、*、-、`、代码块，不要「摘要」「总结」「会话」这类词。
3. 不要以「用户」「对话」开头做转述，直接给主题。
4. 不要引号、不要解释、不要输出多行。
5. 输入里若出现「## 全量摘要」之类的小标题，那只是早先压缩留下的残留，无视它。

示例：
输入：讨论了把 WebUI 插件构建套件独立发到 npm，并处理 trusted publisher 与 OIDC
输出：插件构建套件独立发布

输入：排查图片下载被 fake-ip 网段校验误拒，顺带修了日用量重复插入
输出：fake-ip 图片误拒修复

输入：问 PR #362 的 CI 状态、版本号要不要 bump，最后合并
输出：PR 合并与版本号

输入：解释 AmritaCore 的 session 锁在运行中的行为
输出：会话锁行为说明

反例（出现即视为失败）：「## 全量摘要」「这是一段关于插件的对话，主要……」「摘要：插件开发」
"""

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
    """只做格式归一：取首行、去引号与多余空白。

    不按关键词或 Markdown 语法做定向清洗——模型每次的措辞都不一样，
    正则补丁只会追着上一版输出跑。输出形态由提示词约束，这里只负责
    把「模型给了一段」收成「一行」，以及挡掉会拼出 CQ 码的字符。
    """
    text = (raw or "").strip()
    if not text:
        return None
    #  模型偶尔会在标签后补一句解释，只取第一行
    text = text.splitlines()[0].strip()
    text = text.strip("\"'“”‘’`「」『』 ")
    text = _SPACE_RE.sub(" ", text).strip()
    #  方括号与 @ 会拼出 CQ 码，或被解析成提及；展示层还会再转一次文本段
    text = text.replace("[", "【").replace("]", "】").replace("@", "＠")
    if not text:
        return None
    return text[:TAG_GENERATE_MAX_LEN]


async def generate_session_tag(
    uni_id: str,
    data: AwaredMemory,
    ledger: SessionUsageProxy | None = None,
    preset: Any | None = None,
) -> str | None:
    """生成短标签，失败或超时返回 ``None``。

    Args:
        uni_id: 统一用户 ID，用于记账流的标识
        data: 归档快照，读摘要或尾部对话
        ledger: 传入时把这次调用的用量记进去
        preset: 指定预设；``None`` 时用当前会话预设（测试与离线重跑用）
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
        if preset is None:
            preset = await resolve_preset()
        #  标签只要一句，但 reasoning 与正文共用预算，这里给解析后的预算兜个下限。
        budget = max(resolve_max_output(preset, get_config()), TAG_MAX_OUTPUT)
        preset = preset.model_copy(
            update={
                "max_output": budget,
                #  原生思考模型的 CoT 与正文共用输出预算，这里显式关掉：
                #  关掉才能让那一句标签真的落在 max_output 之内
                "thinking_config": ThinkingConfig(
                    thinking_type="disabled",
                    enable_thinking=False,
                    thinking_effort=None,
                ),
            }
        )
        resp = await asyncio.wait_for(
            get_last_response(call_completion(messages, preset=preset, usage=ledger)),
            timeout=TAG_TIMEOUT,
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).warning("生成会话标签失败。")
        return None
    if not isinstance(resp.content, str) or not resp.content.strip():
        logger.warning("会话标签为空：思考可能耗尽了输出预算，本次跳过。")
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
    """在后台跑一次标签回填，调用方不等待结果。

    Args:
        repo: 用户数据仓库，复用它的锁
        uni_id: 统一用户 ID
        session_id: 归档 id
        created_at: 归档时间戳，防止 id 回收后写错行
        data: 归档快照，任务持有它直到写完
    """
    task = asyncio.create_task(
        backfill_session_tag(repo, uni_id, session_id, created_at, data)
    )
    _background.add(task)
    task.add_done_callback(_background.discard)
