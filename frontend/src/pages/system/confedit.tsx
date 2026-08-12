import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { SearchX } from "lucide-react";
import { api } from "@/lib/api";
import type { ConfeditListData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function ConfeditPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["confedit-list"],
    queryFn: () => api.get<ConfeditListData>("/api/confedit"),
  });

  const items = data?.data.configs ?? [];

  const filtered = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return items;
    return items.filter(
      (c) =>
        c.name.toLowerCase().includes(k) ||
        c.class_name.toLowerCase().includes(k),
    );
  }, [items, keyword]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">配置管理</h1>
        <p className="text-sm text-muted-foreground">编辑各插件的配置</p>
      </div>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle className="text-base">可配置插件</CardTitle>
          <Input
            className="h-9 w-64"
            placeholder="搜索插件名或类名…"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              <div className="h-10 animate-pulse rounded-md bg-muted" />
              <div className="h-10 animate-pulse rounded-md bg-muted" />
            </div>
          ) : filtered.length === 0 ? (
            items.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                没有可配置的插件
              </p>
            ) : (
              <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                <SearchX className="h-8 w-8" />
                <p className="text-sm">没有匹配的插件</p>
              </div>
            )
          ) : (
            <div className="divide-y rounded-md border">
              {filtered.map((c) => (
                <div
                  key={c.name}
                  className="flex items-center gap-3 px-4 py-3 text-sm"
                >
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
