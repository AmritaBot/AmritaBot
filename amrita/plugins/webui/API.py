"""
WebUI 扩展 API

提供给第三方插件（以及 Amrita 内置模块）的扩展点：

- :func:`register_router`     挂载自己的 FastAPI 路由（数据接口）
- :func:`register_ws_channel` 声明自己的 WebSocket 频道
- :func:`broadcast_ws`        向自己的频道广播数据
- :func:`register_page`       注册页面（菜单项 + 前端路由）
- :func:`on_page`             :func:`register_page` 的装饰器版

页面渲染完全交给前端 SPA，后端只负责菜单/路由元数据与 JSON 数据 API。
页面组件有三种来源（见 :func:`register_page`）：前端内置 registry、
``module_url`` 运行期 ESM 模块、``external_url`` iframe 页面。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from .service.authlib import AuthManager, OnetimeTokenData, TokenData, TokenManager
from .service.main import STATIC_PATH, app
from .service.response import JSONResponse
from .service.sidebar import RouteRegistry, SideBarCategory, SideBarItem, SideBarManager

if TYPE_CHECKING:
    from .service.ws import SnapshotProvider


def _register_page(
    path: str,
    page_name: str,
    category: str,
    icon: str | None,
    hidden: bool,
    external_url: str | None,
    module_url: str | None,
) -> None:
    real_hidden = hidden or category == "__HIDDEN__"
    # 注册到路由注册表（所有页面，含隐藏页）
    RouteRegistry().register(
        path=path,
        name=page_name,
        category="隐藏页面" if category == "__HIDDEN__" else category,
        icon=icon,
        hidden=real_hidden,
        external_url=external_url,
        module_url=module_url,
    )
    # 非隐藏页面才进入侧边栏（注册表包含全部，侧边栏只显示可见项）
    if real_hidden:
        return
    if all(cate.name != category for cate in SideBarManager().get_sidebar().items):
        SideBarManager().add_sidebar_category(
            SideBarCategory(name=category, icon=icon or "fa fa-question", url="#")
        )
    SideBarManager().add_sidebar_item(
        category, SideBarItem(name=page_name, url=path, icon=icon)
    )


def register_page(
    path: str,
    page_name: str,
    category: str = "其他功能",
    icon: str | None = None,
    hidden: bool = False,
    external_url: str | None = None,
    module_url: str | None = None,
) -> None:
    """命令式注册页面（:func:`on_page` 的函数版，无需写占位函数）。

    前端按以下顺序决定渲染哪个组件：

    1. 内置 ``registry``（Amrita 自带页面，需要前端构建）
    2. ``module_url``：运行期 ``import()`` 的 ESM 模块，取 ``default`` 作为组件
    3. ``external_url``：``<iframe>`` 嵌入的独立页面
    4. 都没有时渲染占位页

    因此插件只要提供 ``module_url`` 或 ``external_url``，**不需要重新构建前端**。

    Args:
        path: 页面的 URL 路径模式，如 ``/myplugin/stats/{group_id}``
        page_name: 页面名称，显示在侧边栏
        category: 所属分类；``__HIDDEN__`` 表示不加入侧边栏
        icon: 图标标识（前端映射为 lucide 图标名）
        hidden: 是否为隐藏页面（不出现在侧边栏，但保留前端路由）
        external_url: iframe 页面地址，适合用任意技术栈写的独立页面
        module_url: ESM 模块地址，模块需默认导出 React 组件；
            宿主依赖（``react`` / ``react-dom`` / ``react-router-dom``）
            通过 ``window.__AMRITA_HOST__`` 提供，模块应把它们作为 external 处理
    """
    _register_page(path, page_name, category, icon, hidden, external_url, module_url)


def on_page(
    path: str,
    page_name: str,
    category: str = "其他功能",
    icon: str | None = None,
    hidden: bool = False,
    external_url: str | None = None,
    module_url: str | None = None,
):
    """页面路由注册装饰器（:func:`register_page` 的装饰器版）。

    向侧边栏与路由注册表登记页面元数据，前端 SPA 据此生成菜单与路由。
    被装饰的处理函数不再执行（数据渲染已由 JSON API 承担），
    保留该函数体仅为在旧代码中声明页面结构。

    Args:
        path (str): 页面的 URL 路径模式，如 /system/confedit/{owner_name}
        page_name (str): 页面名称，显示在侧边栏
        category (str): 所属分类；__HIDDEN__ 表示不加入侧边栏
        icon (str | None): 图标标识（前端映射为 lucide 图标名）
        hidden (bool): 是否为隐藏页面（不出现在侧边栏，但保留前端路由）
        external_url (str | None): iframe 页面地址，见 :func:`register_page`
        module_url (str | None): 运行期 ESM 模块地址，见 :func:`register_page`
    """

    def decorator(func: Callable[..., Any]):
        _register_page(
            path, page_name, category, icon, hidden, external_url, module_url
        )
        return func

    return decorator


def register_router(
    router: APIRouter,
    *,
    prefix: str = "",
    tags: Sequence[str | Enum] | None = None,
) -> None:
    """把一个 :class:`~fastapi.APIRouter` 挂到 WebUI 的 FastAPI app 上。

    必须在**插件 import 期**调用：SPA 的 catch-all 路由（``/{full_path:path}``）
    挂在 ``driver.on_startup``，晚于它注册的路由会被抢先匹配而永远返回
    ``index.html``。

    路由受 WebUI 的登录中间件保护（``/api`` 前缀返回 401 JSON，
    其他前缀 302 到登录页）。
    """
    app.include_router(router, prefix=prefix, tags=list(tags) if tags else None)


def register_ws_channel(name: str, snapshot: SnapshotProvider | None = None) -> None:
    """声明一个可订阅的 WebSocket 频道。

    未声明的频道名会被 ``/amrita/ui/ws`` 忽略，所以必须先声明再推送。

    Args:
        name: 频道名，客户端用 ``{"action":"subscribe","channels":[name]}`` 订阅
        snapshot: 可选，订阅瞬间调用一次以推送当前状态（同步或异步均可），
            返回 ``None`` 表示本次无快照
    """
    # 延迟导入：service.ws 在 import 期会安装日志捕获 sink，
    # 不能因为「只想注册一个路由」就把它提前拉起
    from .service.ws import hub

    hub.register_channel(name, snapshot)


async def broadcast_ws(channel: str, data: dict[str, Any]) -> None:
    """向某个 WebSocket 频道广播数据（频道需先用 :func:`register_ws_channel` 声明）。"""
    from .service.ws import hub

    await hub.broadcast(channel, data)


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
    "broadcast_ws",
    "get_templates_dir",
    "on_page",
    "register_page",
    "register_router",
    "register_ws_channel",
]
