from __future__ import annotations

import importlib
import importlib.metadata
import platform
import sys

import nonebot
from fastapi import Request
from fastapi.responses import HTMLResponse

from amrita.config import get_amrita_config
from amrita.plugins.webui.API import PageContext, PageResponse, on_page
from amrita.utils.system_health import calculate_system_usage
from amrita.utils.utils import get_amrita_version

from ..main import TemplatesManager, app, try_get_bot
from ..sidebar import SideBarManager


@on_page("/bot/status", "Bot状态", "系统信息")
async def _(ctx: PageContext):
    bot = try_get_bot()
    sys_info = calculate_system_usage()
    return PageResponse(
        "status.html",
        {
            "request": ctx.request,
            "bot_static_info": {  # 机器人静态信息
                "id": bot.self_id if bot else "未连接",
                "name": get_amrita_config().bot_name,
                "version": get_amrita_version(),
                "platform": "OneBot V11",
            },
            "bot_dynamic_info": {  # 机器人动态信息(初始值，将通过API实时更新)
                "status": "online" if bot else "offline",  # 状态: online/offline
                **sys_info,
            },
            "system_info": {  # 系统信息
                "os": sys_info["system_version"],
                "python_version": sys.version,
                "hostname": platform.node(),
            },
        },
    )


@app.get("/bot/plugins", response_class=HTMLResponse)
async def _(request: Request):
    side_bar = SideBarManager().get_sidebar_dump()
    for bar in side_bar:
        if bar.get("name") == "机器人管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child.get("name") == "插件管理":
                    child["active"] = True
                    break
            break
    plugins = nonebot.get_loaded_plugins()
    plugin_list = []
    for plugin in plugins:
        version = "Unknown"
        try:
            version = importlib.metadata.version(plugin.module_name)
        except Exception as e:
            nonebot.logger.warning(f"获取插件 {plugin.module_name} 的版本信息失败: {e}")
        plugin_list.append(
            {
                "name": (plugin.metadata.name if plugin.metadata else plugin.name),
                "homepage": (plugin.metadata.homepage if plugin.metadata else None),
                "is_local": "." in plugin.module_name,
                "type": (
                    (plugin.metadata.type or "Unknown")
                    if plugin.metadata
                    else "Unknown"
                ),
                "description": (
                    plugin.metadata.description or "(还没有介绍呢)"
                    if plugin.metadata
                    else "（还没有介绍呢）"
                ),
                "version": (
                    version
                    if "." not in plugin.module_name
                    else (
                        "(不适用)"
                        if "amrita.plugins." not in plugin.module_name
                        else "Amrita内置插件"
                    )
                ),
            }
        )
    return TemplatesManager().TemplateResponse(
        request,
        "plugins.html",
        context={
            "plugins": plugin_list,
            "plugin_types": ["application", "library"],
            "sidebar_items": side_bar,
        },
    )
