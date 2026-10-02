"""Token 用量统计与持久化（从原 chat.py 抽出）

usage 完全依赖 provider 随响应上报（AmritaCore 1.0 已移除本地分词器），
汇总后写入全局 InsightsModel 与用户/群元数据。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from amrita_core import BillingRecord, debug_log
from amrita_core.utils import gather_usage
from amrita_sense.hook.matcher import MatcherFactory
from nonebot_plugin_amrita.database import InsightsModel

from ...events import ChatUsageRecordedEvent
from ...utils.libchat import add_usage
from ...utils.sql import get_uni_user_id, make_uni_id

if TYPE_CHECKING:
    from amrita_core.chatmanager import ChatObject as CoreChatObject
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot_plugin_amrita.memory import CachedUserDataRepository

__all__ = ["record_usage"]


def _billing_snapshot(chat: CoreChatObject) -> list[BillingRecord]:
    """读取账目快照；DI 上下文未就绪（异常收尾路径）时返回空列表。"""
    try:
        return list(chat.data.billing)
    except RuntimeError:
        return []


async def record_usage(
    chat: CoreChatObject,
    event: MessageEvent,
    cudr: CachedUserDataRepository,
) -> None:
    """统计本次对话 token 用量并持久化到全局洞察与用户/群元数据

    provider 未上报 usage 时只计次、不计 token。
    """
    if chat._di_resp.response is None:
        return

    insights = await InsightsModel.get()
    debug_log(f"获取洞察数据完成，使用计数: {insights.usage_count}")

    usg = chat._di_resp.response.usage
    usage = gather_usage(usg, chat._di_resp.extra_usage) if usg is not None else None
    add_usage(insights, usage)
    await insights.save()
    debug_log(f"更新全局统计完成，使用计数: {insights.usage_count}")

    ins = await cudr.get_metadata(get_uni_user_id(event))
    for d in (
        (
            ins,
            await cudr.get_metadata(make_uni_id(event.user_id, is_group=False)),
        )
        if hasattr(event, "group_id")
        else (ins,)
    ):
        d.called_count
        add_usage(d, usage)
        await cudr.update_metadata(d)

    #  扩展点：用量落库后的钩子（计费、配额、审计的挂载点）
    await MatcherFactory.trigger_event(
        ChatUsageRecordedEvent(
            event=event,
            session_id=get_uni_user_id(event),
            usage=usage,
            billing=_billing_snapshot(chat),
        )
    )
