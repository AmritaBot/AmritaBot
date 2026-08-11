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
    """页面路由注册表：on_page 注册的页面元数据，前端据此生成 SPA 路由。

    与侧边栏不同，这里包含所有页面（含 __HIDDEN__ 页），
    因为隐藏页面同样需要前端路由匹配。
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
    ):
        self._routes.append(
            {
                "path": path,
                "name": name,
                "category": category,
                "icon": icon,
                "hidden": hidden,
            }
        )

    def get_routes(self) -> list[dict]:
        return list(self._routes)
