"""计费接入点 —— 只提供数据出口，不含任何计费实现。

Amrita 不定义价格、不做扣费、不管套餐。这里只负责两件事：

1. **查询侧**：把当前可得的用量读出来（单元当日的 ``called_count`` /
   ``tokens_input`` / ``tokens_output``，以及 ``total_*`` 长期累计），
   供外部计费系统按自己的口径聚合。全局按日序列另有 :func:`get_daily_usage`。

2. **回调侧**：外部实现 :class:`BillingProvider`，用 :func:`register_billing_provider`
   注入，chat 插件在每次用量落库后会调用 :func:`dispatch_usage` 转发逐请求账目
   （:class:`amrita_core.types.billing.BillingRecord` 列表，带请求时刻的价格快照）。
   未注册 provider 时这一路是空转，不产生额外开销。

刻意没有做的：按天归档、价格折算、额度扣减、对账重放。
这些属于接入方的职责，Amrita 只保证账面数据是原始的、可自证的。
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from amrita_core.types.billing import BillingRecord
from nonebot import logger
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


@dataclass(slots=True)
class UsageDispatch:
    """一次对话向 provider 转发的载荷。

    ``units`` 是本次用量实际累加到的计费单元：群聊会同时记到群和个人两条，
    接入方据此判断是否重复计费。``billing`` 为逐请求账目，可能为空
    （provider 未上报用量时只计次、不计 token）。
    """

    session_id: str
    units: list[str] = field(default_factory=list)
    usage: object | None = None
    billing: list[BillingRecord] = field(default_factory=list)


@runtime_checkable
class BillingProvider(Protocol):
    """外部计费系统需要实现的接口（全部可选，实现方按需）。

    两个方法都是协程；Amrita 会在调用处捕获异常并记日志，绝不让接入方的
    故障影响聊天主流程。
    """

    async def on_usage(self, payload: UsageDispatch) -> None:
        """每条用量落库后回调，用于记账、计费、投递队列。"""
        ...

    async def check_quota(self, unit_id: str, requested_tokens: int = 0) -> bool:
        """在调用模型前询问是否仍有额度；返回 ``False`` 表示拒绝本次请求。

        未实现时视为不限。
        """
        ...


_provider: BillingProvider | None = None


def register_billing_provider(provider: BillingProvider | None) -> None:
    """注入（或清除）计费实现。传 ``None`` 解除注册，恢复空转。"""
    global _provider
    _provider = provider
    logger.info(
        "计费 provider {}".format("已注册" if provider is not None else "已注销")
    )


def get_billing_provider() -> BillingProvider | None:
    """取出当前计费实现，未注册时为 ``None``。"""
    return _provider


async def dispatch_usage(payload: UsageDispatch) -> None:
    """把一次用量转给 provider；未注册或 provider 出错都不影响调用方。"""
    provider = _provider
    if provider is None:
        return
    on_usage = getattr(provider, "on_usage", None)
    if on_usage is None:
        return
    with contextlib.suppress(Exception):
        try:
            await on_usage(payload)
        except Exception:
            logger.opt(exception=True).warning("计费 provider.on_usage 执行失败")


async def check_quota(unit_id: str, requested_tokens: int = 0) -> bool:
    """向 provider 询问额度；未注册、未实现或出错一律放行。"""
    provider = _provider
    if provider is None:
        return True
    checker = getattr(provider, "check_quota", None)
    if checker is None:
        return True
    try:
        return bool(await checker(unit_id, requested_tokens))
    except Exception:
        logger.opt(exception=True).warning("计费 provider.check_quota 执行失败")
        return True


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
    "BillingProvider",
    "DailyUsageRow",
    "UnitUsage",
    "UsageDispatch",
    "check_quota",
    "dispatch_usage",
    "get_billing_provider",
    "get_daily_usage",
    "get_unit_usage",
    "iter_unit_usage",
    "register_billing_provider",
)
