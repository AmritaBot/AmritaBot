from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING

import nonebot
from aiologic import Lock
from nonebot import logger
from nonebot.adapters import Bot, MessageSegment

from amrita.config import get_amrita_config
from amrita.utils.rate import TokenBucket
from amrita.utils.send import send_forward_msg_to_target

# 用于跟踪消息发送的计数器和时间戳
_message_tracker = defaultdict(int)
# 异常状态标志
_critical_error_occurred = False
# 线程锁，确保计数器操作的线程安全
_tracker_lock = Lock()
bucket = TokenBucket(
    1 / 7,  # 7s一次
    1,
)
_last_exception_time = 0


# 数据库出现问题时可能导致一直产生错误，这里的设计也是为了账号安全。
async def _check_and_handle_rate_limit():
    """检查消息发送频率并处理速率限制"""
    global _critical_error_occurred, bucket, _last_exception_time
    from amrita.plugins.manager.status_manager import StatusManager

    async with _tracker_lock:
        consume = bucket.consume()
        _message_tracker["admin"] += int(not consume)

        if _message_tracker["admin"] > 7 and not _critical_error_occurred:
            _critical_error_occurred = True
            StatusManager().set_unready(True)
            nonebot.logger.info(
                "严重异常警告！Amrita可能无法从这个错误恢复！之后的推送将被阻断！请立即查看控制台！现在amrita将进入维护模式！"
            )
            await send_to_admin(
                "严重异常警告！Amrita可能无法从这个错误恢复！之后的推送将被阻断！请立即查看控制台！现在amrita将进入维护模式！"
            )
            nonebot.logger.info("Critical error occurred!Rejected pushing!")
            return True

        elif _critical_error_occurred:
            if consume and time.time() - _last_exception_time > 15:
                _critical_error_occurred = False
                _message_tracker["admin"] = 0
                logger.info("[LOGGER] Fall back to logging-ready status.")
            else:
                logger.info("Rejecting pushing due to critical error.")
                return True  # 仍然处于异常状态
        elif consume:
            _message_tracker["admin"] -= 1 if _message_tracker["admin"] > 0 else 0
    StatusManager().set_unready(False)
    return False  # 表示不需要阻断消息发送


if TYPE_CHECKING:
    from nonebot_plugin_alconna.uniseg import Segment, Target


def _admin_target(config) -> "Target":
    from nonebot_plugin_alconna.uniseg import SupportScope, Target

    return Target.group(str(config.admin_group), SupportScope.qq_client)


async def send_to_admin(msg: str, bot: Bot | None = None):
    """发送消息到管理"""
    from nonebot_plugin_alconna.uniseg import UniMessage

    config = get_amrita_config()
    if config.admin_group == -1:
        return nonebot.logger.warning("SEND_TO_ADMIN\n" + msg)
    if bot is None:
        bot = nonebot.get_bot()
    await UniMessage(msg).send(target=_admin_target(config), bot=bot)


async def send_forward_msg_to_admin(
    bot: Bot,
    name: str,
    uin: str,
    msgs: list[str | MessageSegment | "Segment"],
):
    """以合并转发形式发送消息到管理"""
    global _last_exception_time
    if await _check_and_handle_rate_limit():
        return
    _last_exception_time = time.time()

    config = get_amrita_config()
    if config.admin_group == -1:
        text = "".join(
            m.data.get("text", "") if isinstance(m, MessageSegment) else str(m)
            for m in msgs
            if not isinstance(m, MessageSegment) or m.is_text()
        )
        return nonebot.logger.warning("LOG_MSG_FORWARD\n" + text)

    await send_forward_msg_to_target(
        bot, _admin_target(config), name, uin, msgs
    )
