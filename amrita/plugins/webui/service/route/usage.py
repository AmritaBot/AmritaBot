"""用量排行 API —— 基于上下文记录的窗口聚合排行。

数据源为 chat 插件的「静默上下文记录」，这里只做只读聚合，不新增表、不复制常量：
表结构取自 chat 的 ORM 模型，会话标识的解析复用 ``parse_uni_user_id``，
记录保留时长直接读 chat 的运行时配置（``context.record_ttl_hours``）。

模型与配置在首次请求时才导入：webui 插件先于 chat 加载，模块级导入会踩到未初始化的配置。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import cache
from typing import Any

from fastapi import Request
from nonebot import logger
from nonebot_plugin_orm import get_session
from sqlalchemy import case, func, select

from ..main import app
from ..response import fail, ok

#  接口契约：窗口与条数的边界，属于本端点自身的参数约束，不随任何配置变化
_MIN_DAYS = 0.5
_MAX_DAYS = 30.0
_DEFAULT_DAYS = 3.0
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100

_KIND_GROUP = "group"


@cache
def _context_model() -> Any:
    """chat 插件的上下文记录模型（延迟导入，首次调用后缓存）。"""
    from amrita.plugins.chat.models import ContextRecord

    return ContextRecord


@cache
def _parse_uni_id() -> Any:
    """chat 插件的会话标识解析函数（延迟导入，兼容旧格式与平台前缀）。"""
    from amrita.plugins.chat.utils.sql import parse_uni_user_id

    return parse_uni_user_id


def _record_ttl_hours() -> float | None:
    """记录保留时长（小时），0 表示不按时间淘汰；读不到配置时返回 None。"""
    try:
        from amrita.plugins.chat.config import config_manager

        return float(config_manager.config.context.record_ttl_hours)
    except Exception:
        logger.opt(exception=True).debug("读取上下文记录 TTL 失败")
        return None


def _split_uni_id(uni_id: str) -> tuple[str, str]:
    """把会话 ID 拆成 ``(kind, peer_id)``，解析失败时原样返回。"""
    parsed = _parse_uni_id()(uni_id)
    if parsed is None:
        return "unknown", uni_id
    extra, peer = parsed
    return str(extra).lower(), str(peer)


def _as_text(value: Any) -> str | None:
    """sqlite 返回字符串、mysql 返回 datetime，统一裁剪成 ``YYYY-mm-dd HH:MM:SS``。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)[:19]


def _read_number(raw: str, default: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return min(max(value, low), high)


def _read_int(raw: str, default: int, low: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, low), high)


@app.get("/api/usage/ranking")
async def usage_ranking(request: Request):
    """消息用量排行（会话 / 成员两个维度同时返回）。

    查询参数：
    - days: 统计窗口（天，0.5~30，默认 3）；实际可用区间受上下文记录 TTL 限制
    - limit: 每个维度的返回条数（1~100，默认 20）
    """
    params = request.query_params
    days = _read_number(
        params.get("days", str(_DEFAULT_DAYS)), _DEFAULT_DAYS, _MIN_DAYS, _MAX_DAYS
    )
    limit = _read_int(
        params.get("limit", str(_DEFAULT_LIMIT)), _DEFAULT_LIMIT, 1, _MAX_LIMIT
    )

    now = datetime.now()
    since = now - timedelta(days=days)

    record = _context_model()
    messages = func.count()
    media_messages = func.sum(case((record.media_ids.is_not(None), 1), else_=0))

    totals_stmt = select(
        messages.label("msgs"),
        func.count(func.distinct(record.uni_id)).label("sessions"),
        func.count(func.distinct(record.user_id)).label("users"),
    ).where(record.created_at >= since)

    groups_stmt = (
        select(
            record.uni_id.label("uni_id"),
            messages.label("msgs"),
            func.count(func.distinct(record.user_id)).label("users"),
            media_messages.label("media_msgs"),
            func.max(record.created_at).label("last_at"),
        )
        .where(record.created_at >= since)
        .group_by(record.uni_id)
        .order_by(messages.desc())
        .limit(limit)
    )

    users_stmt = (
        select(
            record.user_id.label("user_id"),
            func.max(record.nickname).label("nickname"),
            messages.label("msgs"),
            func.count(func.distinct(record.uni_id)).label("sessions"),
            func.max(record.created_at).label("last_at"),
        )
        .where(record.created_at >= since)
        .group_by(record.user_id)
        .order_by(messages.desc())
        .limit(limit)
    )

    try:
        async with get_session() as session:
            totals_row = (await session.execute(totals_stmt)).first()
            group_rows = (await session.execute(groups_stmt)).all()
            user_rows = (await session.execute(users_stmt)).all()
    except Exception as exc:  # 表缺失（chat 未启用）、库不可达等
        logger.opt(exception=exc).warning("用量排行查询失败")
        return fail(
            500,
            "用量排行查询失败，请检查数据库与 chat 插件状态",
            data={"error": str(exc)},
        )

    groups = []
    for row in group_rows:
        kind, peer = _split_uni_id(row.uni_id)
        groups.append(
            {
                "uni_id": row.uni_id,
                "kind": kind,
                "peer_id": peer,
                "messages": int(row.msgs or 0),
                "users": int(row.users or 0),
                "media_messages": int(row.media_msgs or 0),
                "last_active": _as_text(row.last_at),
            }
        )

    users = [
        {
            "user_id": row.user_id,
            "nickname": row.nickname or "",
            "messages": int(row.msgs or 0),
            "sessions": int(row.sessions or 0),
            "last_active": _as_text(row.last_at),
        }
        for row in user_rows
    ]

    return ok(
        "success",
        data={
            "window": {
                "days": days,
                "since": since.strftime("%Y-%m-%d %H:%M:%S"),
                "until": now.strftime("%Y-%m-%d %H:%M:%S"),
                "ttl_hours": _record_ttl_hours(),
            },
            "totals": {
                "messages": int(totals_row.msgs) if totals_row else 0,
                "sessions": int(totals_row.sessions) if totals_row else 0,
                "users": int(totals_row.users) if totals_row else 0,
            },
            "groups": groups,
            "users": users,
        },
    )
