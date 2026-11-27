"""Chat 插件错误上报到管理员的轻量包装。"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters import Bot

from amrita.utils.admin import send_to_admin


async def send_to_admin_as_error(msg: str, bot: Bot | None = None) -> None:
    logger.error(msg)
    await send_to_admin(msg, bot)
