import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import type { MenuCategory } from "@/lib/menu";
import { Sidebar } from "./Sidebar";

const COLLAPSE_KEY = "amrita-sidebar-collapsed";

/** 应用框架：可折叠侧边栏 + 内容区 */
export function AppShell({ categories }: { categories: MenuCategory[] }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      // localStorage 不可用：忽略
    }
  }, [collapsed]);

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar
        categories={categories}
        activePath={location.pathname}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onNavigate={(path) => navigate(path)}
      />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
