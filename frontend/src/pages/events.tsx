import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, SearchX, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { EventsData } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type Level = "ALL" | "INFO" | "DEBUG" | "WARNING" | "ERROR" | "FATAL";

const LEVEL_COLORS: Record<string, string> = {
  INFO: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  DEBUG: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  WARNING: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  ERROR: "bg-red-500/15 text-red-600 dark:text-red-400",
  FATAL: "bg-purple-500/15 text-purple-600 dark:text-purple-400",
};

function LevelBadge({ level }: { level: string }) {
  const color = LEVEL_COLORS[level] ?? "bg-muted text-muted-foreground";
  return (
    <Badge variant="outline" className={`shrink-0 border-0 ${color}`}>
      {level}
    </Badge>
  );
}

/** 事件查看器：异常事件追溯（时间倒序，支持过滤与详情展开） */
export function EventsPage() {
  const [level, setLevel] = useState<Level>("ALL");
  const [keyword, setKeyword] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["events", level, keyword],
    queryFn: () => {
      const params = new URLSearchParams({ limit: "1000" });
      if (level !== "ALL") params.set("level", level);
      if (keyword.trim()) params.set("keyword", keyword.trim());
      return api.get<EventsData>(`/api/events?${params.toString()}`);
    },
  });

  const events = useMemo(() => data?.data.events ?? [], [data]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">事件查看器</h1>
        <p className="text-sm text-muted-foreground">异常事件追溯</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="w-36">
          <Select value={level} onValueChange={(v) => setLevel(v as Level)}>
            <SelectTrigger className="h-9">
              <SelectValue placeholder="级别" />
            </SelectTrigger>
            <SelectContent>
              {(
                ["ALL", "INFO", "DEBUG", "WARNING", "ERROR", "FATAL"] as Level[]
              ).map((l) => (
                <SelectItem key={l} value={l}>
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Input
          className="h-9 max-w-xs"
          placeholder="搜索关键词…"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setLevel("ALL");
            setKeyword("");
          }}
        >
          <Trash2 className="mr-1 h-4 w-4" /> 清空过滤
        </Button>
        <span className="text-xs text-muted-foreground">
          共 {data?.data.total ?? 0} 条事件
        </span>
      </div>

      {error && (
        <p className="text-sm text-destructive">
          加载事件失败：{error.message}
        </p>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">事件列表</CardTitle>
          <CardDescription>点击条目展开完整堆栈信息</CardDescription>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
              <SearchX className="h-8 w-8" />
              <p className="text-sm">没有匹配的事件</p>
            </div>
          ) : (
            <div className="divide-y">
              {events.map((ev, i) => {
                const isOpen = expanded === i;
                return (
                  <button
                    key={`${ev.time}-${i}`}
                    type="button"
                    className="flex w-full flex-col gap-1 px-2 py-2.5 text-left transition-colors hover:bg-muted/50"
                    onClick={() => setExpanded(isOpen ? null : i)}
                  >
                    <div className="flex items-center gap-2 text-sm">
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: ev.icon_color }}
                      />
                      <LevelBadge level={ev.level} />
                      <span className="min-w-0 flex-1 truncate">{ev.desc}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {ev.time}
                      </span>
                    </div>
                    {isOpen &&
                      (ev.traceback || ev.message) &&
                      ev.message !== "None" && (
                        <pre className="ml-6 mt-1 overflow-x-auto rounded-md bg-muted/50 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                          {ev.traceback ?? ev.message}
                        </pre>
                      )}
                  </button>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
