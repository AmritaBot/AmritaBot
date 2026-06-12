"""WebUI API路由模块

该模块定义了WebUI的API端点，用于处理黑名单管理、消息统计、插件列表等后台管理功能。
"""

from __future__ import annotations

from datetime import datetime
from importlib import metadata
from typing import Literal

import nonebot
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from nonebot import get_bot
from pydantic import BaseModel

from amrita.plugins.manager.blacklist.black import BL_Manager
from amrita.plugins.manager.models import get_usage
from amrita.plugins.webui.service.authlib import TOKEN_KEY, TokenManager
from amrita.plugins.webui.service.response import fail, ok
from amrita.utils.system_health import calculate_system_usage

from ..main import app, try_get_bot
from ..sidebar import SideBarManager


class RequestDataSchema(BaseModel):
    """请求数据模型

    用于黑名单添加接口的数据验证。
    """

    id: str
    type: Literal["group", "user"]
    reason: str


class BlacklistRemoveSchema(BaseModel):
    """黑名单批量删除数据模型

    用于批量删除黑名单条目的数据验证。
    """

    ids: list[str]


@app.get("/api/auth/otk")
async def get_otk(request: Request):
    """获取一次性令牌"""
    access_token = request.cookies.get(TOKEN_KEY)
    if not access_token:
        raise HTTPException(status_code=401, detail="未授权")
    token = await TokenManager().create_one_time_token(access_token)
    return {"token": token}


@app.post("/api/blacklist/add")
async def add_blacklist_item(data: RequestDataSchema):
    """添加黑名单条目

    根据类型（群组或用户）将指定ID添加到黑名单中。

    :param data: 包含ID、类型和原因的请求数据
    :return: 操作结果的JSON响应
    """
    try:
        func = (
            BL_Manager.private_append
            if data.type == "user"
            else BL_Manager.group_append
        )
        await func(data.id, data.reason)
    except Exception as e:
        return fail(500, str(e))
    return ok("已添加到黑名单")


@app.get("/api/chart/messages")
async def get_messages_chart_data():
    """获取消息图表数据

    获取消息统计数据用于图表展示。

    :return: 包含标签和数据的字典
    :raises HTTPException: 当机器人未连接或发生其他错误时
    """
    try:
        bot = get_bot()
        usage = await get_usage(bot.self_id)
        labels = [usage[i].created_at for i in range(len(usage))]
        data = [usage[i].msg_received for i in range(len(usage))]
        return {"labels": labels, "data": data}
    except ValueError:
        raise HTTPException(status_code=500, detail="Bot未连接")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart/today-usage")
async def get_msg_io_status_chart_data():
    """获取今日消息使用量图表数据

    获取今日消息收发统计数据用于图表展示。

    :return: 包含收发标签和数据的字典
    :raises HTTPException: 当机器人未连接、数据不存在或发生其他错误时
    """
    try:
        bot = get_bot()
        usage_data = await get_usage(bot.self_id)
        for i in usage_data:
            if i.created_at == datetime.now().strftime("%Y-%m-%d"):
                data = [i.msg_received, i.msg_sent]
                break
        else:
            raise HTTPException(status_code=404, detail="数据不存在")
        return {"labels": ["收", "发"], "data": data}
    except ValueError:
        raise HTTPException(status_code=500, detail="Bot未连接")
    except HTTPException as e:
        raise e


@app.post("/api/blacklist/remove-batch/{type}")
async def remove_blacklist_batch(data: BlacklistRemoveSchema, type: str):
    """批量删除黑名单条目

    根据类型批量删除黑名单中的条目。

    :param data: 包含要删除的ID列表的数据
    :param type: 黑名单类型（"user" 或 "group"）
    :return: 操作结果的JSON响应
    """
    for id in data.ids:
        if type == "user":
            await BL_Manager.private_remove(id)
        elif type == "group":
            await BL_Manager.group_remove(id)
    return ok("已批量移除")


@app.post("/api/blacklist/remove/{type}/{id}")
async def remove_blacklist_item(request: Request, type: str, id: str):
    """删除单个黑名单条目

    根据类型和ID删除黑名单中的条目。

    :param request: HTTP请求对象
    :param type: 黑名单类型（"user" 或 "group"）
    :param id: 要删除的条目ID
    :return: 操作结果的JSON响应
    """
    func = BL_Manager.private_remove if type == "user" else BL_Manager.group_remove
    await func(id)
    return ok("已移除")


@app.get("/api/plugins/list")
async def list_plugins(request: Request):
    """获取插件列表

    获取已加载插件的详细信息列表。

    :param request: HTTP请求对象
    :return: 插件信息列表
    """
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
                plugin.metadata.description or "(还没有介绍呢)"
                if plugin.metadata
                else "（还没有介绍呢）"
            ),
            "version": (
                metadata.version(plugin.module_name)
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
    return plugin_list


@app.get("/api/bot/status", response_class=JSONResponse)
async def get_bot_status(request: Request):
    """获取机器人状态

    获取机器人在线状态、系统使用情况和侧边栏项目信息。

    :param request: HTTP请求对象
    :return: 包含机器人状态信息的JSON响应
    """
    side_bar = SideBarManager().get_sidebar_dump()
    for bar in side_bar:
        if bar.get("name") == "机器人管理":
            bar["active"] = True
            break
    return JSONResponse(
        {
            "status": "online" if try_get_bot() else "offline",
            **calculate_system_usage(),
            "sidebar_items": side_bar,
        }
    )
