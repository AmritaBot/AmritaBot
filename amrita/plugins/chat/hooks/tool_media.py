"""工具返回多模态内容的入库钩子。"""

from nonebot import logger

from amrita.plugins.chat.events import StepToolReturnEvent, on_tool_return
from amrita.plugins.chat.utils.context_store import ingest_tool_media


@on_tool_return(priority=5).handle()
async def _ingest_tool_media(event: StepToolReturnEvent) -> None:
    """工具返回后、写回上下文前，把其中的 data URI 图片写入本地存储。"""
    try:
        await ingest_tool_media(event.result)
    except Exception:
        logger.opt(exception=True).warning("工具返回的图片入库失败")
