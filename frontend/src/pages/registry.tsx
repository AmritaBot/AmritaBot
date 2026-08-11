/**
 * 页面组件注册表 —— 前端唯一注册点
 *
 * key 为后端 on_page / 核心路由注册表中的路径模式（FastAPI 风格），
 * value 为懒加载页面组件。
 *
 * 菜单 API 返回的路径未在此注册时，前端渲染 PagePlaceholder 占位页。
 */
import { lazy, type ComponentType } from "react";

export const registry: Record<string, ComponentType> = {
  // 仪表盘 & 系统
  "/dashboard": lazy(() =>
    import("@/pages/dashboard").then((m) => ({ default: m.DashboardPage })),
  ),
  "/bot/status": lazy(() =>
    import("@/pages/bot/status").then((m) => ({ default: m.BotStatusPage })),
  ),
  "/bot/logs": lazy(() =>
    import("@/pages/bot/logs").then((m) => ({ default: m.LogsPage })),
  ),
  "/events": lazy(() =>
    import("@/pages/events").then((m) => ({ default: m.EventsPage })),
  ),
  "/bot/plugins": lazy(() =>
    import("@/pages/bot/plugins").then((m) => ({ default: m.BotPluginsPage })),
  ),
  "/bot/config": lazy(() =>
    import("@/pages/bot/config").then((m) => ({ default: m.BotConfigPage })),
  ),
  "/dbmeta": lazy(() =>
    import("@/pages/bot/dbmeta").then((m) => ({ default: m.DbMetaPage })),
  ),

  // 用户管理
  "/blacklists": lazy(() =>
    import("@/pages/user/blacklist").then((m) => ({
      default: m.BlacklistPage,
    })),
  ),
  "/permissions/groups": lazy(() =>
    import("@/pages/user/permissions").then((m) => ({
      default: m.PermissionsPage,
    })),
  ),
  "/permissions/groups/{name}": lazy(() =>
    import("@/pages/user/perm-group").then((m) => ({
      default: m.PermGroupDetailPage,
    })),
  ),
  "/permissions/users/{user_id}": lazy(() =>
    import("@/pages/user/user-permission").then((m) => ({
      default: m.UserPermissionPage,
    })),
  ),
  "/permissions/group-scopes/{group_id}": lazy(() =>
    import("@/pages/user/user-permission").then((m) => ({
      default: m.GroupPermissionPage,
    })),
  ),

  // 系统管理
  "/system/confedit": lazy(() =>
    import("@/pages/system/confedit").then((m) => ({
      default: m.ConfeditPage,
    })),
  ),
  "/system/confedit/{owner_name}": lazy(() =>
    import("@/pages/system/confedit-editor").then((m) => ({
      default: m.ConfeditEditorPage,
    })),
  ),

  // 聊天管理
  "/manage/chat/insights": lazy(() =>
    import("@/pages/manage/insights").then((m) => ({
      default: m.InsightsPage,
    })),
  ),
  "/manage/chat/models": lazy(() =>
    import("@/pages/manage/models").then((m) => ({ default: m.ModelsPage })),
  ),
  "/manage/chat/prompts": lazy(() =>
    import("@/pages/manage/prompts").then((m) => ({ default: m.PromptsPage })),
  ),
  "/manage/chat/mcp": lazy(() =>
    import("@/pages/manage/mcp").then((m) => ({ default: m.McpPage })),
  ),
};
