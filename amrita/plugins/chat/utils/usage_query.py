"""用量查询侧 —— 读 ``nonebot_plugin_amrita`` 的计费表，供排行、对账、外部计费系统取数。

数据源是 ``nonebot_plugin_amrita`` 的 ``amrita_user_metadata`` / ``amrita_global_insights``：
当日字段会在跨天后被懒清零，``total_*`` 才是单调累计值。这里只做只读聚合，
不做价格折算、额度扣减，也不新增表。

归属说明：查询要 import ``nonebot_plugin_amrita`` 的 ORM 模型，那是 chat 插件的
依赖，所以放在 chat 插件里，而不是 bot 级的 :mod:`amrita.utils.billing`。后者被
``amrita.API`` 在导入期带入，早于插件管理器登记 ``nonebot_plugin_amrita``，
在模块级 import 会让 chat 插件的 ``require`` 直接失败。

chat 插件加载完成之后才能调用本模块的函数；webui 等先于 chat 加载的插件，
按本仓库既有做法在请求处理时延迟导入。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from nonebot_plugin_amrita.database import GlobalInsights, UserMetadata
from nonebot_plugin_orm import get_session
from sqlalchemy import select

_DEFAULT_DAILY_DAYS = 7
_MAX_DAILY_DAYS = 90
_MAX_PAGE_SIZE = 500


@dataclass(slots=True)
class UnitUsage:
    """一个计费单元的用量快照。

    ``unit_id`` 是 Amrita 的会话标识（``QQPlatform_Group_{群号}`` /
    ``QQPlatform_Private_{QQ}``），群与私聊共用一张表，接入方按前缀自行区分。
    当日字段会在跨天后被懒清零，``total_*`` 才是单调累计值。
    """

    unit_id: str
    calls: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    total_calls: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    last_active: datetime | None = None

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def total_tokens(self) -> int:
        return self.total_tokens_input + self.total_tokens_output


@dataclass(slots=True)
class DailyUsageRow:
    """全局按日用量（``amrita_global_insights``，一行一天）。"""

    date: str
    usage_count: int = 0
    token_input: int = 0
    token_output: int = 0

    @property
    def token_total(self) -> int:
        return self.token_input + self.token_output


async def get_unit_usage(unit_id: str) -> UnitUsage | None:
    """读取单个单元的用量快照；单元从未产生用量时返回 ``None``。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(UserMetadata).where(UserMetadata.user_id == unit_id)
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return UnitUsage(
        unit_id=row.user_id,
        calls=row.called_count or 0,
        tokens_input=row.tokens_input or 0,
        tokens_output=row.tokens_output or 0,
        total_calls=row.total_called_count or 0,
        total_tokens_input=row.total_input_token or 0,
        total_tokens_output=row.total_output_token or 0,
        last_active=row.last_active,
    )


async def iter_unit_usage(
    active_since: datetime | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[UnitUsage]:
    """翻页列出单元用量快照，可按 ``last_active`` 过滤出近期活跃的单元。"""
    limit = max(1, min(limit, _MAX_PAGE_SIZE))
    offset = max(0, offset)
    stmt = select(UserMetadata).order_by(UserMetadata.last_active.desc())
    if active_since is not None:
        stmt = stmt.where(UserMetadata.last_active >= active_since)
    stmt = stmt.limit(limit).offset(offset)
    async with get_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        UnitUsage(
            unit_id=row.user_id,
            calls=row.called_count or 0,
            tokens_input=row.tokens_input or 0,
            tokens_output=row.tokens_output or 0,
            total_calls=row.total_called_count or 0,
            total_tokens_input=row.total_input_token or 0,
            total_tokens_output=row.total_output_token or 0,
            last_active=row.last_active,
        )
        for row in rows
    ]


async def get_daily_usage(days: int = _DEFAULT_DAILY_DAYS) -> list[DailyUsageRow]:
    """读取全局按日用量，按日期升序返回（最多 90 天）。"""
    days = max(1, min(days, _MAX_DAILY_DAYS))
    stmt = select(GlobalInsights).order_by(GlobalInsights.date.desc()).limit(days)
    async with get_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        DailyUsageRow(
            date=row.date,
            usage_count=row.usage_count or 0,
            token_input=row.token_input or 0,
            token_output=row.token_output or 0,
        )
        for row in reversed(rows)
    ]


__all__: Sequence[str] = (
    "DailyUsageRow",
    "UnitUsage",
    "get_daily_usage",
    "get_unit_usage",
    "iter_unit_usage",
)
