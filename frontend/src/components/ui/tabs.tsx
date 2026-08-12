import { createContext, useContext, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * 自写 Tabs：按钮自身对比度高亮 + 内容淡入动效
 *
 * - 高亮：active 按钮自身切换为背景色 + 阴影 + 描边（对比度区分，不遮挡文字）
 * - 动效：按钮背景/文字颜色过渡，切换时内容区淡入上移（tw-animate-css）
 */

interface TabsContextValue {
  value: string;
  setValue: (v: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext() {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("Tabs 组件必须在 Tabs 内使用");
  return ctx;
}

export function Tabs({
  defaultValue,
  className,
  children,
}: {
  defaultValue: string;
  className?: string;
  children: ReactNode;
}) {
  const [value, setValue] = useState(defaultValue);
  return (
    <TabsContext.Provider value={{ value, setValue }}>
      <div className={cn("flex flex-col gap-3", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex h-9 w-fit items-center gap-1 rounded-lg bg-muted p-1",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: ReactNode;
}) {
  const { value: active, setValue } = useTabsContext();
  const isActive = active === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isActive}
      data-tab={value}
      onClick={() => setValue(value)}
      className={cn(
        "inline-flex h-7 items-center justify-center whitespace-nowrap rounded-md px-3 text-sm font-medium transition-all duration-200",
        // active：背景色 + 阴影 + 描边形成高对比度高亮；inactive：弱化文字
        isActive
          ? "bg-background text-foreground shadow-sm ring-1 ring-border"
          : "text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: ReactNode;
}) {
  const { value: active } = useTabsContext();
  if (active !== value) return null;
  return (
    <div
      role="tabpanel"
      data-tab-panel={value}
      className={cn(
        "animate-in fade-in slide-in-from-top-1 duration-200",
        className,
      )}
    >
      {children}
    </div>
  );
}
