/**
 * 明暗主题切换（模块级单例，供任意组件订阅）
 * - 记忆 localStorage，未设置时跟随系统
 * - 与 use-ws 相同模式：模块级 store + useSyncExternalStore，
 *   保证 Sidebar、Toaster 等任意组件共享同一主题状态
 */
import { useCallback, useSyncExternalStore } from "react";

type Theme = "light" | "dark";
const STORAGE_KEY = "amrita-theme";

function getInitialTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

let currentTheme: Theme = getInitialTheme();
const listeners = new Set<() => void>();

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  localStorage.setItem(STORAGE_KEY, theme);
}

// 模块加载时立即应用一次（避免首帧闪烁）
applyTheme(currentTheme);

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Theme {
  return currentTheme;
}

/** 切换主题（全局生效，所有订阅组件同步重渲染） */
export function setTheme(theme: Theme) {
  currentTheme = theme;
  applyTheme(theme);
  listeners.forEach((l) => l());
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme]);

  return { theme, toggleTheme };
}
