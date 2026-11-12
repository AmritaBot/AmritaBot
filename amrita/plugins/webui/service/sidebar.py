from __future__ import annotations

from pydantic import BaseModel
from typing_extensions import Self


class SideBarItem(BaseModel):
    name: str
    icon: str | None = None
    url: str | None = None
    active: bool = False
    hidden: bool = False


class SideBarCategory(BaseModel):
    name: str
    icon: str | None = None
    url: str | None = None
    active: bool = False
    children: list[SideBarItem] = []


class SideBar(BaseModel):
    items: list[SideBarCategory] = [
        SideBarCategory(
            name="仪表盘", icon="fa fa-dashboard", url="/dashboard", active=False
        ),
        SideBarCategory(
            name="机器人管理",
            icon="fa fa-robot",
            url="#",
            active=False,
            children=[
                SideBarItem(name="插件管理", url="/bot/plugins", active=False),
                SideBarItem(name="Dotenv编辑", url="/bot/config", active=False),
            ],
        ),
        SideBarCategory(
            name="用户管理",
            icon="fas fa-users",
            url="#",
            active=False,
            children=[
                SideBarItem(name="权限管理", url="/users/permissions", active=False),
                SideBarItem(name="黑名单管理", url="/user/blacklist", active=False),
            ],
        ),
        SideBarCategory(
            name="系统信息",
            icon="fas fa-info-circle",
            url="#",
            active=False,
            children=[],
        ),
    ]


class SideBarManager:
    _instance = None
    sidebar: SideBar

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.sidebar = SideBar()
        return cls._instance

    def get_sidebar(self) -> SideBar:
        return self.sidebar

    def get_sidebar_dump(self) -> list[dict]:
        return [item.model_dump() for item in self.sidebar.items]

    def add_sidebar_category(self, item: SideBarCategory):
        self.sidebar.items.append(item)

    def set_sidebar_items(self, items: list[SideBarCategory]):
        self.sidebar.items = items

    def add_sidebar_item(self, category: str, item: SideBarItem):
        for category_item in self.sidebar.items:
            if category_item.name == category:
                category_item.children.append(item)
                return

    def set_sidebar_item(self, category: str, item: SideBarItem):
        for category_item in self.sidebar.items:
            if category_item.name == category:
                category_item.children = [item]
                return

    def get_sidebar_dump_with_hidden(self) -> list[dict]:
        """导出侧边栏结构（含 hidden 项），供菜单 API 使用。"""
        return [item.model_dump() for item in self.sidebar.items]


class RouteRegistry:
    """页面路由注册表：on_page / register_page 注册的页面元数据，前端据此生成 SPA 路由。

    与侧边栏不同，这里包含所有页面（含 __HIDDEN__ 页），
    因为隐藏页面同样需要前端路由匹配。

    ``external_url`` / ``module_dir`` / ``module_url`` 用于让第三方插件在不重新构建
    前端的前提下接入自定义页面（见 :func:`amrita.plugins.webui.API.register_page`）。

    优先用 ``module_dir``：插件只声明产物名，URL、版本参数与可用性都由宿主解析。
    ``module_url`` 是 1.10 起的旧接口，保留给已发布的插件，宿主原样下发不做改写。
    """

    _instance: Self | None = None
    _routes: list[dict]

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._routes = []
        return cls._instance

    def register(
        self,
        path: str,
        name: str,
        category: str,
        icon: str | None = None,
        hidden: bool = False,
        external_url: str | None = None,
        module_dir: str | None = None,
        module_url: str | None = None,
    ):
        self._routes.append(
            {
                "path": path,
                "name": name,
                "category": category,
                "icon": icon,
                "hidden": hidden,
                "external_url": external_url,
                "module_dir": module_dir,
                "module_url": module_url,
            }
        )

    def get_routes(self) -> list[dict]:
        """导出路由元数据，插件页面的 module_url 在这里按目录解析。

        解析放在导出时而非注册时：产物可能在插件 import 之后才落盘
        （构建与启动的先后顺序不固定），注册时算 mtime 会拿到过期值。
        """
        from .plugin_assets import resolve_plugin_assets

        routes: list[dict] = []
        for route in self._routes:
            item = dict(route)
            module_dir = item.get("module_dir")
            if isinstance(module_dir, str):
                info = resolve_plugin_assets(module_dir)
                available = bool(info.get("available"))
                # 产物缺失时不给 URL：前端会渲染占位页，而不是让用户点进去撞 404
                item["module_url"] = info["module_url"] if available else None
                item["module_available"] = available
                item["module_reason"] = info.get("reason")
            elif isinstance(item.get("module_url"), str):
                # 旧接口：插件自己给完整 URL，宿主无法校验可用性，一律当作可用
                item["module_available"] = True
                item["module_reason"] = None
            else:
                item["module_url"] = None
                item["module_available"] = None
                item["module_reason"] = None
            routes.append(item)
        return routes
