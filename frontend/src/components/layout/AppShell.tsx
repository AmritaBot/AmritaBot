import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import type { MenuCategory } from "@/lib/menu";
import { Sidebar } from "./Sidebar";

const COLLAPSE_KEY = "amrita-sidebar-collapsed";

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", handler);
    setMatches(mql.matches);
    return () => mql.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

/** 应用框架：可折叠侧边栏（移动端抽屉）+ 内容区 */
export function AppShell({ categories }: { categories: MenuCategory[] }) {
  const location = useLocation();
  const navigate = useNavigate();
  // 桌面端折叠状态（localStorage 持久化）
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  // 移动端抽屉（<lg）打开状态
  const [mobileOpen, setMobileOpen] = useState(false);
  const isMobile = useMediaQuery("(max-width: 1023px)");

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      // localStorage 不可用：忽略
    }
  }, [collapsed]);

  // 路由变化时关闭移动端抽屉（点菜单项导航后自动收起）
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      {/* 移动端抽屉遮罩 */}
      {isMobile && mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}
      <Sidebar
        categories={categories}
        activePath={location.pathname}
        collapsed={collapsed}
        mobileOpen={isMobile && mobileOpen}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onCloseMobile={() => setMobileOpen(false)}
        onNavigate={(path) => navigate(path)}
      />
      <main className="flex-1 overflow-y-auto p-3 lg:p-6">
        {/* 移动端汉堡按钮（桌面隐藏） */}
        <div className="mb-3 flex items-center gap-2 lg:hidden">
          <button
            onClick={() => setMobileOpen(true)}
            title="打开菜单"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold tracking-tight">AmritaBot</span>
        </div>
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
