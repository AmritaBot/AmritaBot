import { useEffect, useMemo, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { useWs, type LogEvent } from "@/hooks/use-ws";
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
import { Switch } from "@/components/ui/switch";

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

export function LogsPage() {
  // 订阅 logs 频道（全局单连接，切页不重连）
  const { logs, connected } = useWs({ channels: ["logs"] });

  const [level, setLevel] = useState<Level>("ALL");
  const [keyword, setKeyword] = useState("");
  const [tracking, setTracking] = useState(true);
  const [frozenLogs, setFrozenLogs] = useState<LogEvent[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  // 关闭追踪时冻结当前快照
  useEffect(() => {
    if (!tracking) setFrozenLogs(logs);
  }, [tracking, logs]);

  const visible = tracking ? logs : frozenLogs;

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return visible.filter((l) => {
      if (level !== "ALL" && l.title !== level) return false;
      if (kw && !`${l.title} ${l.desc}`.toLowerCase().includes(kw))
        return false;
      return true;
    });
  }, [visible, level, keyword]);

  // 自动滚动到底部（追踪开启时跟随新日志）
  useEffect(() => {
    const el = scrollRef.current;
    if (el && autoScrollRef.current && tracking) {
      el.scrollTop = el.scrollHeight;
    }
  }, [filtered.length, tracking]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    autoScrollRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  const count = filtered.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">实时日志</h1>
          <p className="text-sm text-muted-foreground">
            实时日志流（WebSocket）
            {connected ? " · 已连接" : " · 未连接"}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Switch
              checked={tracking}
              onCheckedChange={setTracking}
              aria-label="追踪新日志"
            />
            追踪
          </label>
          <Button variant="ghost" size="sm" onClick={() => setKeyword("")}>
            <Trash2 className="mr-1 h-4 w-4" /> 清空过滤
          </Button>
        </div>
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
        <span className="text-xs text-muted-foreground">
          {tracking ? "" : "追踪已关闭 · "}显示 {count} 条
        </span>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">日志流</CardTitle>
          <CardDescription>
            本次 Bot 启动以来的日志 · 滚轮上滑暂停自动跟随
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="h-[60vh] overflow-y-auto rounded-md border bg-muted/30 font-mono text-xs"
          >
            {filtered.length === 0 ? (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                {connected ? "暂无日志" : "等待连接…"}
              </div>
            ) : (
              filtered.map((l, i) => (
                <div
                  key={`${l.time}-${i}`}
                  className="flex items-start gap-2 border-b border-border/50 px-3 py-1.5 last:border-0"
                >
                  <span className="shrink-0 text-muted-foreground">
                    {l.time}
                  </span>
                  <LevelBadge level={l.title} />
                  <span className="break-all">{l.desc}</span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
