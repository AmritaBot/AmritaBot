"""消息防抖：把静默窗口内的多条消息合并成一次请求的用户输入。

窗口由 ``function.chat_debounce_window`` 控制（秒），<=0 时关闭。
缓冲以 (会话 uni_id, 用户) 为粒度：群聊里每人各自一个窗口，避免把不同人
的发言并进同一次请求；私聊的会话本身就是单人，等价于会话级。
用户发完文字紧接着补一张图，也会落在同一批里。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ...utils.sql import get_uni_user_id

__all__ = ["collect_batch"]

#  待合并事件：键为 (会话 ID, 用户 ID)
_buffers: defaultdict[tuple[str, str], list[MessageEvent]] = defaultdict(list)
#  新消息到达时置位，用于重置批首的静默计时
_signals: dict[tuple[str, str], asyncio.Event] = {}


def _key(event: MessageEvent) -> tuple[str, str]:
    return (get_uni_user_id(event), event.get_user_id())


async def collect_batch(
    event: MessageEvent, matcher: Matcher, window: float
) -> list[MessageEvent] | None:
    """把事件放进防抖缓冲。

    Returns:
        批首返回本批事件列表（至少含当前事件）；
        非批首返回 None，调用方应直接结束本次流程。
    """
    key = _key(event)
    signal = _signals.get(key)
    if signal is not None:
        #  已有批首在等待，本条只入桶并触发一次计时重置
        _buffers[key].append(event)
        signal.set()
        matcher.stop_propagation()
        return None

    signal = asyncio.Event()
    _signals[key] = signal
    _buffers[key].append(event)
    try:
        while True:
            try:
                await asyncio.wait_for(signal.wait(), timeout=window)
            except asyncio.TimeoutError:
                break
            signal.clear()
    finally:
        batch = _buffers.pop(key, [event])
        _signals.pop(key, None)
    return batch
