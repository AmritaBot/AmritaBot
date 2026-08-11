import { Suspense, useMemo } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MenuData } from "@/lib/types";
import { groupMenu } from "@/lib/menu";
import { generateMenuRoutes } from "@/lib/router";
import { useAuth } from "@/hooks/use-auth";
import { AppShell } from "@/components/layout/AppShell";
import { NotFound } from "@/components/shared/PagePlaceholder";
import { LoginPage } from "@/pages/login";

function Splash() {
  return (
    <div className="grid min-h-screen place-items-center bg-background text-foreground">
      <div className="flex flex-col items-center gap-3">
        <img
          src="/static/images/logo-96.png"
          alt="AmritaBot"
          className="h-16 w-16 rounded-full"
        />
        <span className="text-lg font-semibold tracking-tight">AmritaBot WebUI</span>
        <div className="h-1 w-32 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-sidebar-primary" />
        </div>
      </div>
    </div>
  );
}

export function App() {
  const { user, loading } = useAuth();

  const { data: menuData } = useQuery({
    queryKey: ["menu"],
    queryFn: () => api.get<MenuData>("/api/meta/menu"),
    enabled: !!user,
  });

  const categories = useMemo(
    () => groupMenu(menuData?.data.routes ?? []),
    [menuData],
  );
  const menuRoutes = useMemo(
    () => generateMenuRoutes(menuData?.data.routes ?? []),
    [menuData],
  );

  if (loading) return <Splash />;

  // 未登录：首页（/）即登录面板，登录 API 为 POST /api/auth/login
  if (!user) return <LoginPage />;

  return (
    <Suspense fallback={<Splash />}>
      <Routes>
        <Route path="/" element={<AppShell categories={categories} />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          {menuRoutes.map(({ path, Component }) => (
            <Route key={path} path={path} element={<Component />} />
          ))}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
