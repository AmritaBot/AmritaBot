/**
 * 菜单 API → React Router 路由
 *
 * 后端 on_page / 核心路由注册表是唯一数据源：
 * 启动时拉取 /api/meta/menu，动态生成路由与侧边栏。
 * 前端只通过 pages/registry.tsx 提供「路由模式 → 组件」映射。
 */
import { lazy, type ComponentType } from "react";
import type { MenuRoute } from "./types";
import { toRouterPath } from "./menu";

/** 页面组件注册表：路由模式 → 懒加载组件 */
import { registry } from "@/pages/registry";

const PagePlaceholder = lazy(() =>
  import("@/components/shared/PagePlaceholder").then((m) => ({
    default: m.PagePlaceholder,
  })),
);

export interface GeneratedRoute {
  /** React Router 路径（去掉开头 /，作为嵌套路由相对路径） */
  path: string;
  /** 原始菜单路由（用于 Sidebar 高亮等） */
  route: MenuRoute;
  /** 懒加载组件（未注册 → 占位页） */
  Component: ComponentType;
}

/** 生成菜单路由列表（含未注册占位） */
export function generateMenuRoutes(routes: MenuRoute[]): GeneratedRoute[] {
  return routes.map((route) => {
    const Registered = registry[route.path];
    const Component: ComponentType =
      Registered ?? (() => <PagePlaceholder name={route.name} />);
    return {
      path: toRouterPath(route.path).replace(/^\//, ""),
      route,
      Component,
    };
  });
}
