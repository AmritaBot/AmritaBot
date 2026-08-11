"""WebUI 数据 API 路由模块

RESTful 风格：读 = GET，写 = POST。统一响应 { success, message, data }。
"""

from __future__ import annotations

import importlib.metadata
import logging
from datetime import datetime
from typing import Literal

import nonebot
from fastapi import HTTPException
from pydantic import BaseModel

from amrita.plugins.manager.blacklist.black import BL_Manager
from amrita.plugins.manager.models import get_usage
from amrita.plugins.webui.service.authlib import TOKEN_KEY, TokenManager
from amrita.plugins.webui.service.response import fail, ok
from amrita.utils.logging import LoggingData
from amrita.utils.system_health import calculate_system_health, calculate_system_usage

from ..main import app, try_get_bot

logger = logging.getLogger(__name__)


class BlacklistActionSchema(BaseModel):
    """黑名单操作请求模型。"""

    action: Literal["add", "remove"]
    reason: str = ""


class BlacklistBatchSchema(BaseModel):
    """黑名单批量移除请求模型。"""

    type: Literal["user", "group"]
    ids: list[str]


@app.get("/api/auth/otk")
async def get_otk(request):
    """获取一次性令牌"""
    access_token = request.cookies.get(TOKEN_KEY)
    if not access_token:
        raise HTTPException(status_code=401, detail="未授权")
    token = await TokenManager().create_one_time_token(access_token)
    return ok("success", data={"token": token})


@app.get("/api/dashboard")
async def get_dashboard():
    """仪表盘聚合数据：消息统计、系统健康、最近活动。"""
    bot = try_get_bot()
    usage = await get_usage(bot.self_id) if bot else []
    usage.sort(key=lambda u: u.id)

    if usage:
        message_stats = {
            "labels": [u.created_at for u in usage],
            "data": [u.msg_received + u.msg_sent for u in usage],
        }
        msg_io_status = {
            "labels": ["收", "发"],
            "data": [usage[-1].msg_received, usage[-1].msg_sent],
        }
        total_message = usage[-1].msg_received + usage[-1].msg_sent
    else:
        message_stats = {"labels": ["Bot未连接"], "data": [0]}
        msg_io_status = {"labels": ["Bot未连接"], "data": [0]}
        total_message = 0

    events = (await LoggingData.get()).data[-200:]
    events.reverse()

    return ok(
        "success",
        data={
            "bot_connected": bot is not None,
            "total_message": total_message,
            "health": calculate_system_health()["overall_health"],
            "loaded_plugins": len(nonebot.get_loaded_plugins()),
            "message_stats": message_stats,
            "msg_io_status": msg_io_status,
            "recent_activity": [
                {
                    "title": ac.log_level,
                    "desc": ac.description,
                    "time": ac.time.strftime("%Y-%m-%d %H:%M:%S"),
                    "icon_color": ac.color,
                    "icon": ac.icon,
                }
                for ac in events
            ],
        },
    )


@app.get("/api/bot/status")
async def get_bot_status():
    """机器人状态 + 系统用量。"""
    return ok(
        "success",
        data={
            "status": "online" if try_get_bot() else "offline",
            **calculate_system_usage(),
        },
    )


@app.get("/api/bot/plugins")
async def list_plugins():
    """已加载插件列表。"""
    plugins = nonebot.get_loaded_plugins()
    plugin_list = [
        {
            "name": (plugin.metadata.name if plugin.metadata else plugin.name),
            "homepage": (plugin.metadata.homepage if plugin.metadata else None),
            "is_local": "." in plugin.module_name,
            "type": (
                (plugin.metadata.type or "Unknown") if plugin.metadata else "Unknown"
            ),
            "description": (
                plugin.metadata.description or "（还没有介绍呢）"
                if plugin.metadata
                else "（还没有介绍呢）"
            ),
            "version": (
                importlib.metadata.version(plugin.module_name)
                if "." not in plugin.module_name
                else (
                    "(不适用)"
                    if "amrita.plugins." not in plugin.module_name
                    else "Amrita内置插件"
                )
            ),
        }
        for plugin in plugins
    ]
    return ok("success", data={"plugins": plugin_list})


@app.get("/api/blacklists")
async def get_blacklists():
    """全量黑名单（用户 + 群组）。"""
    data = await BL_Manager.get_full_blacklist()
    return ok(
        "success",
        data={
            "groups": [
                {
                    "id": k,
                    "reason": v.reason,
                    "added_time": v.time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for k, v in data["group"].items()
            ],
            "users": [
                {
                    "id": k,
                    "reason": v.reason,
                    "added_time": v.time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for k, v in data["private"].items()
            ],
        },
    )


@app.post("/api/blacklists/{type}/{id}")
async def blacklist_action(type: str, id: str, data: BlacklistActionSchema):
    """黑名单增删：action = add（需 reason）/ remove。"""
    try:
        if data.action == "add":
            func = (
                BL_Manager.private_append
                if type == "user"
                else BL_Manager.group_append
            )
            await func(id, data.reason)
            return ok("已添加到黑名单")
        func = (
            BL_Manager.private_remove if type == "user" else BL_Manager.group_remove
        )
        await func(id)
        return ok("已移除")
    except Exception:
        logger.exception("Failed to %s blacklist item %s", data.action, id)
        return fail(500, "黑名单操作失败")


@app.post("/api/blacklists/actions/batch")
async def blacklist_batch_remove(data: BlacklistBatchSchema):
    """批量移除黑名单条目。"""
    for id in data.ids:
        func = (
            BL_Manager.private_remove
            if data.type == "user"
            else BL_Manager.group_remove
        )
        await func(id)
    return ok("已批量移除")
