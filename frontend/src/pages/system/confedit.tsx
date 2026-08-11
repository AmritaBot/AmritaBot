import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { GripVertical } from "lucide-react";
import { api } from "@/lib/api";
import type { ConfeditListData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ConfigItem {
  name: string;
  class_name: string;
}

const ORDER_KEY = "confedit-list-order";

export function ConfeditPage() {
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["confedit-list"],
    queryFn: () => api.get<ConfeditListData>("/api/confedit"),
  });

  // 本地排序状态：默认按 API 顺序，用户拖拽后持久化到 localStorage
  const [items, setItems] = useState<ConfigItem[]>([]);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  useEffect(() => {
    const configs = data?.data.configs ?? [];
    if (configs.length === 0) return;
    // 尝试读取本地顺序（仅保留仍存在的插件名）
    try {
      const saved = JSON.parse(
        localStorage.getItem(ORDER_KEY) ?? "[]",
      ) as string[];
      const savedOrder = saved
        .map((name) => configs.find((c) => c.name === name))
        .filter((c): c is ConfigItem => c !== undefined);
      const rest = configs.filter((c) => !saved.includes(c.name));
      setItems([...savedOrder, ...rest]);
    } catch {
      setItems(configs);
    }
  }, [data]);

  // 拖拽排序
  function handleDrop(targetIndex: number) {
    if (dragIndex === null || dragIndex === targetIndex) return;
    setItems((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragIndex, 1);
      if (moved === undefined) return prev;
      next.splice(targetIndex, 0, moved);
      localStorage.setItem(ORDER_KEY, JSON.stringify(next.map((c) => c.name)));
      return next;
    });
    setDragIndex(null);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">配置管理</h1>
        <p className="text-sm text-muted-foreground">
          编辑各插件的配置· 拖动行可调整顺序
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">可配置插件</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              <div className="h-10 animate-pulse rounded-md bg-muted" />
              <div className="h-10 animate-pulse rounded-md bg-muted" />
            </div>
          ) : items.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              没有可配置的插件
            </p>
          ) : (
            <div className="divide-y rounded-md border">
              {items.map((c, i) => (
                <div
                  key={c.name}
                  draggable
                  onDragStart={() => setDragIndex(i)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => handleDrop(i)}
                  onDragEnd={() => setDragIndex(null)}
                  className={`flex items-center gap-3 px-4 py-3 text-sm transition-colors ${
                    dragIndex === i ? "bg-muted/60 opacity-60" : ""
                  } ${dragIndex !== null ? "cursor-grabbing" : "cursor-grab"}`}
                >
                  <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/50" />
                  <span className="w-24 shrink-0 font-medium">{c.name}</span>
                  <code className="flex-1 truncate font-mono text-xs text-muted-foreground">
                    {c.class_name}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      navigate(`/system/confedit/${encodeURIComponent(c.name)}`)
                    }
                  >
                    编辑配置
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
