"""菜单 / 路由注册表 API

以 RouteRegistry（on_page 注册）为单一数据源，
前端据此生成侧边栏菜单与 React Router 路由。
"""

from __future__ import annotations

from amrita.utils.utils import get_amrita_version

from ..main import app
from ..response import ok
from ..sidebar import RouteRegistry

# 核心页面元数据（无对应 on_page 装饰器的页面在此统一注册）
_CORE_ROUTES = [
    {
        "path": "/dashboard",
        "name": "仪表盘",
        "category": "仪表盘",
        "icon": "layout-dashboard",
        "hidden": False,
    },
    {
        "path": "/bot/status",
        "name": "Bot状态",
        "category": "系统信息",
        "icon": "activity",
        "hidden": False,
    },
    {
        "path": "/bot/logs",
        "name": "实时日志",
        "category": "系统信息",
        "icon": "scroll-text",
        "hidden": False,
    },
    {
        "path": "/events",
        "name": "事件查看器",
        "category": "系统信息",
        "icon": "history",
        "hidden": False,
    },
    {
        "path": "/bot/plugins",
        "name": "插件管理",
        "category": "机器人管理",
        "icon": "puzzle",
        "hidden": False,
    },
    {
        "path": "/bot/config",
        "name": "Dotenv编辑",
        "category": "机器人管理",
        "icon": "file-cog",
        "hidden": False,
    },
    {
        "path": "/blacklists",
        "name": "黑名单管理",
        "category": "用户管理",
        "icon": "shield-ban",
        "hidden": False,
    },
    {
        "path": "/permissions/groups",
        "name": "权限管理",
        "category": "用户管理",
        "icon": "key-round",
        "hidden": False,
    },
    {
        "path": "/permissions/groups/{name}",
        "name": "权限组详情",
        "category": "用户管理",
        "icon": None,
        "hidden": True,
    },
    {
        "path": "/permissions/users/{user_id}",
        "name": "用户权限",
        "category": "用户管理",
        "icon": None,
        "hidden": True,
    },
    {
        "path": "/permissions/group-scopes/{group_id}",
        "name": "群组权限",
        "category": "用户管理",
        "icon": None,
        "hidden": True,
    },
    {
        "path": "/dbmeta",
        "name": "数据库元信息",
        "category": "系统信息",
        "icon": "database",
        "hidden": False,
    },
    {
        "path": "/system/confedit",
        "name": "配置管理",
        "category": "系统管理",
        "icon": "settings",
        "hidden": False,
    },
    {
        "path": "/system/confedit/{owner_name}",
        "name": "配置编辑器",
        "category": "系统管理",
        "icon": None,
        "hidden": True,
    },
    {
        "path": "/manage/chat/insights",
        "name": "信息统计",
        "category": "聊天管理",
        "icon": "bar-chart-3",
        "hidden": False,
    },
    {
        "path": "/manage/chat/models",
        "name": "模型预设",
        "category": "聊天管理",
        "icon": "cpu",
        "hidden": False,
    },
    {
        "path": "/manage/chat/prompts",
        "name": "提示词预设",
        "category": "聊天管理",
        "icon": "message-square-text",
        "hidden": False,
    },
    {
        "path": "/manage/chat/mcp",
        "name": "MCP服务器",
        "category": "聊天管理",
        "icon": "server",
        "hidden": False,
    },
]


@app.get("/api/meta/menu")
async def get_menu():
    """获取全部页面路由注册表（含隐藏页），前端据此生成菜单与路由。"""
    routes = list(_CORE_ROUTES) + RouteRegistry().get_routes()
    return ok(
        "success",
        data={
            "routes": routes,
            "version": get_amrita_version(),
        },
    )
