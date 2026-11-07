"""LLM 工具：``read_context`` —— 按需读取群聊静默上下文。

未被触发的群消息不再进入 LLM 记忆，而是由
:mod:`amrita.plugins.chat.utils.context_store` 静默落库；本工具是模型读取这些
记录的入口（当模型想知道"刚才群里聊了什么"时调用）。

工具注册到全局 :class:`~amrita_core.tools.manager.ToolsManager` 单例，
由 :mod:`amrita.plugins.chat` 在插件加载时导入本模块完成注册。
"""

from __future__ import annotations

from collections.abc import Sequence

from amrita_core import (
    FunctionDefinitionSchema,
    FunctionParametersSchema,
    FunctionPropertySchema,
    TextContent,
    ToolContext,
    on_tools,
)
from amrita_core.types import TOOL_RESULT_CONTENT, Content, ImageContent, ImageUrl

from ...config import config_manager
from ..context_store import ContextEntry, load_media_data_uri, read_context_entries
from ..preset import is_multimodal_enabled

READ_CONTEXT_TOOL_NAME = "read_context"

_READ_CONTEXT_DEFINITION = FunctionDefinitionSchema(
    name=READ_CONTEXT_TOOL_NAME,
    description=(
        "读取当前会话最近记录的群聊上下文。\n"
        "当你不确定刚才群里聊了什么、需要补充背景信息，或用户提到"
        "「之前/刚刚说过」的内容时调用本工具。\n"
        "返回内容按时间正序排列，每条记录为 XML 格式"
        '（<msg role="群主/管理员/普通成员" name="昵称" uid="QQ号" '
        'time="2026-09-19 Saturday 15:24:37">内容</msg>），'
        "time 属性为消息发送时间。\n"
        "消息附带的图片会作为图片内容块一并返回，紧随对应的文本之后。"
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


def _image_block(data_uri: str) -> ImageContent:
    """把 ``data:<mime>;base64,...`` 还原成图片内容块。"""
    return ImageContent(image_url=ImageUrl(url=data_uri))


async def _collect_images(
    entries: Sequence[ContextEntry], budget: int
) -> dict[int, list[ImageContent]]:
    """按记录下标收集要还原的图片，总量不超过 ``budget``（0 表示不还原）。"""
    images: dict[int, list[ImageContent]] = {}
    if budget <= 0:
        return images
    remaining = budget
    #  预算优先给最近的记录：条目按时间正序排列，越靠后越接近当前对话，
    #  按正序分配会让最新的图先被挤掉，与 expand_media_in_messages 的口径也不一致
    for index in range(len(entries) - 1, -1, -1):
        if remaining <= 0:
            break
        for media_id in entries[index].media_ids[:remaining]:
            data_uri = await load_media_data_uri(media_id)
            if data_uri is None:
                #  媒体可能已按 TTL 淘汰，跳过即可，不影响文本记录
                continue
            images.setdefault(index, []).append(_image_block(data_uri))
            remaining -= 1
    return images


@on_tools(
    _READ_CONTEXT_DEFINITION,
    custom_run=True,
    enable_if=lambda: config_manager.config.context.enable,
)
async def read_context(tool_ctx: ToolContext) -> TOOL_RESULT_CONTENT:
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

    entries = await read_context_entries(chat_object.session_id, limit, keyword)
    if not entries:
        return (
            "没有符合条件的上下文记录。"
            if keyword
            else "当前会话还没有记录任何上下文。"
        )
    header = (
        f"以下是最新的 {len(entries)} 条群聊上下文记录（时间正序，"
        "早于当前对话，仅供参考）："
    )

    if not any(entry.media_ids for entry in entries):
        return header + "\n" + "\n".join(entry.content for entry in entries)

    budget = (
        config_manager.config.context.read_context_max_images
        if await is_multimodal_enabled()
        else 0
    )
    images = await _collect_images(entries, budget)

    #  有图时按「记录 -> 该记录的图」顺序交错排布，保持图片与发送者的对应关系
    blocks: list[Content] = []
    lines: list[str] = [header]
    for index, entry in enumerate(entries):
        lines.append(entry.content)
        attached = images.get(index)
        if attached:
            blocks.append(TextContent(text="\n".join(lines)))
            blocks.extend(attached)
            lines = []
    if lines:
        blocks.append(TextContent(text="\n".join(lines)))
    return blocks
