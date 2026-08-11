/** 菜单 / 路由工具 */

import type { MenuRoute } from "./types";

/**
 * FastAPI 路径模式 → React Router 路径模式
 * /system/confedit/{owner_name} → /system/confedit/:owner_name
 * 参数名保持原样（与后端字段、页面 useParams 一致，避免 camelCase 错位）
 */
export function toRouterPath(path: string): string {
  return path.replace(/\{(\w+)\}/g, ":$1");
}

/** 侧边栏分组：按 category 分组（排除 hidden），保持注册顺序 */
export interface MenuCategory {
  name: string;
  items: MenuRoute[];
}

export function groupMenu(routes: MenuRoute[]): MenuCategory[] {
  const visible = routes.filter((r) => !r.hidden);
  const map = new Map<string, MenuCategory>();
  for (const route of visible) {
    let cat = map.get(route.category);
    if (!cat) {
      cat = { name: route.category, items: [] };
      map.set(route.category, cat);
    }
    cat.items.push(route);
  }
  return [...map.values()];
}

/** 判断菜单项当前是否激活 */
export function isRouteActive(
  routePath: string,
  locationPath: string,
): boolean {
  const pattern = toRouterPath(routePath);
  const patternParts = pattern.split("/").filter(Boolean);
  const locationParts = locationPath.split("/").filter(Boolean);
  if (patternParts.length !== locationParts.length) return false;
  return patternParts.every(
    (part, i) => part.startsWith(":") || part === locationParts[i],
  );
}
