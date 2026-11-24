"""计费接入点（回调侧）—— 只提供数据出口，不含任何计费实现。

Amrita 不定义价格、不做扣费、不管套餐。这里只管一件外部可插拔的事：外部实现
:class:`BillingProvider`，用 :func:`register_billing_provider` 注入，chat 插件在每次
用量落库后调用 :func:`dispatch_usage` 转发逐请求账目（:class:`amrita_core.types.billing.BillingRecord`
列表，带请求时刻的价格快照）；调用模型之前另有 :func:`check_quota` 询问额度。
未注册 provider 时这几路都是空转，不产生额外开销。

本模块属于 bot 级接口，被 ``amrita.API`` 在导入期带入，而 ``amrita.API`` 又经由
``amrita.plugins.manager`` 早于 ``amrita.plugins.chat`` 加载。因此这里只允许依赖
``amrita_core`` 这类与 NoneBot 插件管理器无关的包；一旦在模块级 import
``nonebot_plugin_amrita``，该包会在插件管理器登记之前进入 ``sys.modules``，
之后 chat 里的 ``require`` 会因缺少 ``__plugin__`` 失败。

读 ``nonebot_plugin_amrita`` 表的查询侧（单元用量快照、按日累计）属于 chat 插件
的地盘，放在 :mod:`amrita.plugins.chat.utils.usage_query`，不要搬回这里。
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from amrita_core.types.billing import BillingRecord
from nonebot import logger


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


__all__: Sequence[str] = (
    "BillingProvider",
    "UsageDispatch",
    "check_quota",
    "dispatch_usage",
    "get_billing_provider",
    "register_billing_provider",
)
