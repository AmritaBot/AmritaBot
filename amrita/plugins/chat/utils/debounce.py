"""消息防抖：把静默窗口内的多条消息合并成一次请求的用户输入。

窗口由 ``function.chat_debounce_window`` 控制（秒），<=0 时关闭；单批条数与
总时长分别由 ``chat_debounce_max_messages`` / ``chat_debounce_max_wait`` 兜底，
避免持续发言把批次无限拖长或撑大内存。

缓冲以 (会话 uni_id, 用户) 为粒度：群聊里每人各自一个窗口，避免把不同人
的发言并进同一次请求；私聊的会话本身就是单人，等价于会话级。
用户发完文字紧接着补一张图，也会落在同一批里。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from .sql import get_uni_user_id

__all__ = ["collect_batch", "has_active_batch"]

#  待合并事件：键为 (会话 ID, 用户 ID)
_buffers: defaultdict[tuple[str, str], list[MessageEvent]] = defaultdict(list)
#  新消息到达时置位，用于重置批首的静默计时
_signals: dict[tuple[str, str], asyncio.Event] = {}


def _key(event: MessageEvent) -> tuple[str, str]:
    return (get_uni_user_id(event), event.get_user_id())


def has_active_batch(event: MessageEvent) -> bool:
    """该事件所属会话是否正处于防抖批次中。

    供消息规则放行批次内的后续消息（例如没命中关键词的图片）。
    """
    return _key(event) in _signals


async def collect_batch(
    event: MessageEvent,
    matcher: Matcher,
    window: float,
    *,
    max_messages: int = 0,
    max_wait: float = 0.0,
) -> list[MessageEvent] | None:
    """把事件放进防抖缓冲。

    Args:
        window: 静默窗口，距最后一条消息超过该时长即收口。
        max_messages: 单批最大条数，<=0 表示不限制。
        max_wait: 单批最长存活时长（秒），<=0 表示不限制。

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
    loop = asyncio.get_running_loop()
    started = loop.time()
    #  用 asyncio.wait 而不是 wait_for：后者在内层 future 已完成时会把取消吞掉
    waiter = asyncio.ensure_future(signal.wait())
    try:
        while True:
            timeout = window
            if max_wait > 0:
                timeout = min(timeout, max_wait - (loop.time() - started))
            if timeout <= 0:
                break
            done, _ = await asyncio.wait({waiter}, timeout=timeout)
            if not done:
                break
            signal.clear()
            if max_messages > 0 and len(_buffers[key]) >= max_messages:
                break
            waiter = asyncio.ensure_future(signal.wait())
    except BaseException:
        #  批首被取消 / 出错：保留缓冲交给下一条消息接手，避免这批消息静默丢失
        _signals.pop(key, None)
        raise
    finally:
        waiter.cancel()
    batch = _buffers.pop(key, [event])
    _signals.pop(key, None)
    return batch
