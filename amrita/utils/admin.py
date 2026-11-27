"""管理员通知推送与速率保护：按平台 Sender 分发，不绑定单一适配器。"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable

import nonebot
from aiologic import Lock
from nonebot import logger
from nonebot.adapters import Bot

from amrita.config import get_amrita_config
from amrita.platform.dto import GROUP, Scope
from amrita.utils.rate import TokenBucket
from amrita.utils.send import (
    ForwardItem,
    _item_to_text,
    resolve_sender,
    send_forward_msg,
)

# 用于跟踪消息发送的计数器和时间戳
_message_tracker: defaultdict[str, int] = defaultdict(int)
# 异常状态标志
_critical_error_occurred = False
# 线程锁，确保计数器操作的线程安全
_tracker_lock = Lock()
bucket = TokenBucket(
    1 / 7,  # 7s一次
    1,
)
_last_exception_time = 0.0


# 数据库出现问题时可能导致一直产生错误，这里的设计也是为了账号安全。
async def _check_and_handle_rate_limit() -> bool:
    """检查消息发送频率并处理速率限制。"""
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


def _admin_scope(bot: Bot, admin_group: int) -> Scope:
    """按 Bot 所属适配器构造管理员群 Scope。"""
    module = type(bot).__module__
    platform = "telegram" if "nonebot.adapters.telegram" in module else "qq"
    return Scope(platform=platform, kind=GROUP, id=str(admin_group))


def _resolve_admin_bot(bot: Bot | None) -> Bot | None:
    if bot is not None:
        return bot
    try:
        return nonebot.get_bot()
    except Exception:
        return None


async def send_to_admin(msg: str, bot: Bot | None = None) -> None:
    """发送纯文本通知到管理员群；未配置管理群或无可用 Bot 时降级写日志。"""
    config = get_amrita_config()
    if config.admin_group == -1:
        nonebot.logger.warning("SEND_TO_ADMIN\n" + msg)
        return
    target_bot = _resolve_admin_bot(bot)
    if target_bot is None:
        nonebot.logger.warning("SEND_TO_ADMIN (no active bot)\n" + msg)
        return
    scope = _admin_scope(target_bot, config.admin_group)
    sender = resolve_sender(target_bot, scope)
    if sender is None:
        nonebot.logger.warning("SEND_TO_ADMIN (no sender)\n" + msg)
        return
    await sender.send_text(msg)


async def send_forward_msg_to_admin(
    bot: Bot,
    name: str,
    uin: str,
    msgs: Iterable[ForwardItem],
) -> None:
    """发送多段异常/日志信息到管理员群，受频率保护与熔断控制。"""
    global _last_exception_time
    if await _check_and_handle_rate_limit():
        return
    _last_exception_time = time.time()

    items = list(msgs)
    config = get_amrita_config()
    if config.admin_group == -1:
        nonebot.logger.warning(
            "LOG_MSG_FORWARD\n".join(
                text for item in items if (text := _item_to_text(item))
            )
        )
        return

    scope = _admin_scope(bot, config.admin_group)
    await send_forward_msg(bot, scope, name=name, uin=uin, msgs=items)


__all__ = ["send_forward_msg_to_admin", "send_to_admin"]
