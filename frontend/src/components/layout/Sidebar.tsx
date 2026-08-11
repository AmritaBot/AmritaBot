import {
  Activity,
  BarChart3,
  Cpu,
  Database,
  FileCog,
  History,
  KeyRound,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Puzzle,
  ScrollText,
  Server,
  Settings,
  ShieldBan,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useTheme } from "@/hooks/use-theme";
import { useAuth } from "@/hooks/use-auth";
import type { MenuCategory } from "@/lib/menu";

/** 后端 icon 名 → lucide 组件映射 */
const ICON_MAP: Record<string, LucideIcon> = {
  "layout-dashboard": LayoutDashboard,
  activity: Activity,
  puzzle: Puzzle,
  "file-cog": FileCog,
  "shield-ban": ShieldBan,
  "key-round": KeyRound,
  database: Database,
  settings: Settings,
  "bar-chart-3": BarChart3,
  cpu: Cpu,
  "message-square-text": MessageSquareText,
  server: Server,
  "scroll-text": ScrollText,
  history: History,
};

function resolveIcon(name: string | null | undefined): LucideIcon {
  if (!name) return Activity;
  return ICON_MAP[name] ?? Activity;
}

export function Sidebar({
  categories,
  activePath,
  collapsed,
  onToggleCollapse,
  onNavigate,
}: {
  categories: MenuCategory[];
  activePath: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNavigate: (path: string) => void;
}) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();

  return (
    <aside
      className={`flex h-screen shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] duration-200 ${
        collapsed ? "w-14" : "w-60"
      }`}
    >
      <div className="flex h-14 items-center justify-between border-b px-3">
        {!collapsed && (
          <div className="flex items-center gap-2 overflow-hidden">
            <span className="text-lg font-semibold tracking-tight">AmritaBot</span>
            <span className="rounded-full bg-sidebar-primary px-2 py-0.5 text-xs font-medium text-sidebar-primary-foreground">
              WebUI
            </span>
          </div>
        )}
        <button
          onClick={onToggleCollapse}
          title={collapsed ? "展开侧边栏" : "折叠侧边栏"}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-sidebar-accent"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        {categories.map((cat) => (
          <div key={cat.name} className="mb-2">
            {!collapsed && (
              <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                {cat.name}
              </p>
            )}
            {cat.items.map((item) => {
              const Icon = resolveIcon(item.icon);
              const active = activePath.startsWith(item.path);
              return (
                <button
                  key={item.path}
                  onClick={() => onNavigate(item.path)}
                  title={collapsed ? item.name : undefined}
                  className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors ${
                    collapsed ? "justify-center px-0" : ""
                  } ${
                    active
                      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60"
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && <span className="truncate">{item.name}</span>}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t p-2">
        {collapsed ? (
          <div className="flex flex-col items-center gap-1">
            <button
              onClick={toggleTheme}
              title="切换主题"
              className="rounded-md p-1.5 hover:bg-sidebar-accent"
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
              )}
            </button>
            <button
              onClick={() => void logout()}
              title="登出"
              className="rounded-md p-1.5 hover:bg-sidebar-accent"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-sm text-muted-foreground">
              {user?.username ?? ""}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={toggleTheme}
                title="切换主题"
                className="rounded-md p-1.5 hover:bg-sidebar-accent"
              >
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </button>
              <button
                onClick={() => void logout()}
                title="登出"
                className="rounded-md p-1.5 hover:bg-sidebar-accent"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
