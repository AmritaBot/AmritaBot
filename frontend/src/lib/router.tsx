/**
 * 菜单 API -> React Router 路由
 *
 * 后端 on_page / register_page 是唯一数据源：
 * 启动时拉取 /api/meta/menu，动态生成路由与侧边栏。
 *
 * 页面组件按以下顺序解析：
 * 1. 前端内置 registry（Amrita 自带页面，需前端构建）
 * 2. route.module_url：运行期 ESM 模块（第三方插件，无需重建前端）
 * 3. route.external_url：iframe 页面（第三方插件，无需重建前端）
 * 4. 都没有时渲染占位页
 */
import { lazy, type ComponentType } from "react";
import type { MenuRoute } from "./types";
import { toRouterPath } from "./menu";

/** 页面组件注册表：路由模式 -> 懒加载组件 */
import { registry } from "@/pages/registry";
import { ExternalPage } from "@/components/shared/ExternalPage";
import { RemoteModulePage } from "@/components/shared/RemoteModulePage";

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
  /** 懒加载组件（未注册 -> 占位页） */
  Component: ComponentType;
}

/** 第三方插件页面：优先运行期 ESM 模块，其次 iframe，最后占位页 */
function resolveExtensionComponent(route: MenuRoute): ComponentType {
  const { name, module_url, external_url } = route;
  if (module_url) {
    return () => <RemoteModulePage name={name} url={module_url} />;
  }
  if (external_url) {
    return () => <ExternalPage name={name} url={external_url} />;
  }
  return () => <PagePlaceholder name={name} />;
}

/** 生成菜单路由列表（含未注册占位） */
export function generateMenuRoutes(routes: MenuRoute[]): GeneratedRoute[] {
  return routes.map((route) => {
    const Component: ComponentType =
      registry[route.path] ?? resolveExtensionComponent(route);
    return {
      path: toRouterPath(route.path).replace(/^\//, ""),
      route,
      Component,
    };
  });
}
