"""LLM 工具：``read_context`` —— 按需读取群聊静默上下文。

未被触发的群消息不再进入 LLM 记忆，而是由
:mod:`amrita.plugins.chat.utils.context_store` 静默落库；本工具是模型读取这些
记录的入口（当模型想知道"刚才群里聊了什么"时调用）。

工具注册到全局 :class:`~amrita_core.tools.manager.ToolsManager` 单例，
由 :mod:`amrita.plugins.chat` 在插件加载时导入本模块完成注册。
"""

from __future__ import annotations

from amrita_core import (
    FunctionDefinitionSchema,
    FunctionParametersSchema,
    FunctionPropertySchema,
    ToolContext,
    on_tools,
)

from ...config import config_manager
from ..context_store import read_context_records

READ_CONTEXT_TOOL_NAME = "read_context"

_READ_CONTEXT_DEFINITION = FunctionDefinitionSchema(
    name=READ_CONTEXT_TOOL_NAME,
    description=(
        "读取当前会话最近记录的群聊上下文。\n"
        "当你不确定刚才群里聊了什么、需要补充背景信息，或用户提到"
        "「之前/刚刚说过」的内容时调用本工具。\n"
        "返回内容按时间正序排列，格式与正常聊天记录一致"
        "（[角色][时间][昵称（QQ号）]说:内容）。"
    ),
    parameters=FunctionParametersSchema(
        type="object",
        properties={
            "limit": FunctionPropertySchema(
                type="integer",
                description=(
                    "要读取的最近记录条数，省略时使用服务端默认值，"
                    "超出服务端上限时按上限返回。"
                ),
            ),
            "keyword": FunctionPropertySchema(
                type="string",
                description="可选关键字，仅返回包含该关键字的记录。",
            ),
        },
        required=[],
    ),
)


def _parse_limit(raw: object) -> int:
    """解析模型传入的 ``limit``，并夹到 ``[1, read_context_limit]`` 区间内。"""
    upper = config_manager.config.context.read_context_limit
    if isinstance(raw, bool):
        return upper
    if isinstance(raw, int):
        return min(max(raw, 1), upper)
    if isinstance(raw, str):
        try:
            return min(max(int(raw.strip()), 1), upper)
        except ValueError:
            return upper
    return upper


@on_tools(
    _READ_CONTEXT_DEFINITION,
    custom_run=True,
    enable_if=lambda: config_manager.config.context.enable,
)
async def read_context(tool_ctx: ToolContext) -> str:
    chat_object = tool_ctx.ctx.chat_object
    if chat_object is None:
        return "无法确定当前会话，暂时不能读取上下文记录。"

    limit = _parse_limit(tool_ctx.data.get("limit"))
    raw_keyword = tool_ctx.data.get("keyword")
    keyword = (
        raw_keyword.strip()
        if isinstance(raw_keyword, str) and raw_keyword.strip()
        else None
    )

    records = await read_context_records(chat_object.session_id, limit, keyword)
    if not records:
        return (
            "没有符合条件的上下文记录。"
            if keyword
            else "当前会话还没有记录任何上下文。"
        )
    header = (
        f"以下是最新的 {len(records)} 条群聊上下文记录（时间正序，"
        "早于当前对话，仅供参考）："
    )
    return header + "\n" + "\n".join(records)
