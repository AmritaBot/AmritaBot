/**
 * Toaster 封装：主题跟随全局 useTheme（模块级单例）
 * - 深色模式下 toast 使用项目 CSS 变量（--card 等），与页面配色一致
 * - richColors 的语义色（success/error 等）保留 sonner 自带适配
 */
import { Toaster as Sonner, type ToasterProps } from "sonner";
import { useTheme } from "@/hooks/use-theme";

export function Toaster(props: ToasterProps) {
  const { theme } = useTheme();

  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      richColors
      toastOptions={{
        duration: 4000,
      }}
      // 普通 toast 颜色跟随项目主题（light/dark 各自取 --card 变量）
      style={
        {
          "--normal-bg": "var(--card)",
          "--normal-border": "var(--border)",
          "--normal-text": "var(--card-foreground)",
          "--normal-hover-bg": "var(--card)",
          "--toast-bg": "var(--card)",
          "--toast-border": "var(--border)",
          "--toast-text": "var(--card-foreground)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
}