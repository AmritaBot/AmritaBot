"""
WebUI 页面注册 API

提供 on_page 装饰器用于注册页面元数据（侧边栏 + 路由注册表）。
不再渲染服务端模板 —— 页面渲染完全交给前端 SPA，
后端只负责菜单/路由元数据与 JSON 数据 API。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .service.authlib import AuthManager, OnetimeTokenData, TokenData, TokenManager
from .service.main import STATIC_PATH, app
from .service.response import JSONResponse
from .service.sidebar import RouteRegistry, SideBarCategory, SideBarItem, SideBarManager


def on_page(
    path: str,
    page_name: str,
    category: str = "其他功能",
    icon: str | None = None,
    hidden: bool = False,
):
    """页面路由注册装饰器。

    向侧边栏与路由注册表登记页面元数据，前端 SPA 据此生成菜单与路由。
    被装饰的处理函数不再执行（数据渲染已由 JSON API 承担），
    保留该函数体仅为在旧代码中声明页面结构。

    Args:
        path (str): 页面的 URL 路径模式，如 /system/confedit/{owner_name}
        page_name (str): 页面名称，显示在侧边栏
        category (str): 所属分类；__HIDDEN__ 表示不加入侧边栏
        icon (str | None): 图标标识（前端映射为 lucide 图标名）
        hidden (bool): 是否为隐藏页面（不出现在侧边栏，但保留前端路由）
    """
    real_hidden = hidden or category == "__HIDDEN__"

    def decorator(func: Callable[..., Any]):
        # 注册到路由注册表（所有页面，含隐藏页）
        RouteRegistry().register(
            path=path,
            name=page_name,
            category="隐藏页面" if category == "__HIDDEN__" else category,
            icon=icon,
            hidden=real_hidden,
        )
        # 非隐藏页面才进入侧边栏（注册表包含全部，侧边栏只显示可见项）
        if not real_hidden:
            if all(
                cate.name != category for cate in SideBarManager().get_sidebar().items
            ):
                SideBarManager().add_sidebar_category(
                    SideBarCategory(
                        name=category, icon=icon or "fa fa-question", url="#"
                    )
                )
            SideBarManager().add_sidebar_item(
                category, SideBarItem(name=page_name, url=path, icon=icon)
            )
        return func

    return decorator


def get_templates_dir() -> Path:
    """兼容占位：模板目录已废弃，返回静态目录。"""
    return STATIC_PATH


__all__ = [
    "STATIC_PATH",
    "AuthManager",
    "JSONResponse",
    "OnetimeTokenData",
    "RouteRegistry",
    "SideBarCategory",
    "SideBarItem",
    "SideBarManager",
    "TokenData",
    "TokenManager",
    "app",
    "get_templates_dir",
    "on_page",
]
