import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWs } from "@/hooks/use-ws";
import { ApiError, api } from "@/lib/api";
import type {
  PluginEntry,
  PluginListData,
  PluginState,
  PluginStoreData,
  PluginStoreEntry,
  PluginTask,
  PluginTaskState,
} from "@/lib/types";

const STATE_LABEL: Record<PluginState, string> = {
  running: "运行中",
  pending_enable: "重启后启用",
  pending_remove: "重启后移除",
  load_failed: "加载失败",
  disabled: "未启用",
  not_installed: "未安装",
};

const STATE_CLASS: Record<PluginState, string> = {
  running:
    "border-transparent bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  pending_enable:
    "border-transparent bg-amber-500/15 text-amber-600 dark:text-amber-400",
  pending_remove:
    "border-transparent bg-orange-500/15 text-orange-600 dark:text-orange-400",
  load_failed:
    "border-transparent bg-red-500/15 text-red-600 dark:text-red-400",
  disabled: "border-transparent bg-muted text-muted-foreground",
  not_installed: "border-transparent bg-muted text-muted-foreground",
};

const KIND_LABEL: Record<string, string> = {
  builtin: "内置",
  amrita_pkg: "Amrita 插件",
  nonebot_pkg: "NoneBot 插件",
  local: "本地",
};

const TASK_LABEL: Record<PluginTaskState, string> = {
  pending: "排队中",
  running: "进行中",
  succeeded: "已完成",
  failed: "失败",
};

const TASK_CLASS: Record<PluginTaskState, string> = {
  pending: "border-transparent bg-muted text-muted-foreground",
  running:
    "border-transparent bg-amber-500/15 text-amber-600 dark:text-amber-400",
  succeeded:
    "border-transparent bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  failed: "border-transparent bg-red-500/15 text-red-600 dark:text-red-400",
};

const PAGE_SIZE = 20;

/** ``nonebot.adapters.onebot.v11`` -> ``onebot.v11``，徽章里不必带全路径 */
function adapterLabel(module: string) {
  return module.replace(/^nonebot\.adapters\./, "");
}

function StateBadge({ state }: { state: PluginState }) {
  return <Badge className={STATE_CLASS[state]}>{STATE_LABEL[state]}</Badge>;
}

function isFinished(task: PluginTask) {
  return task.state === "succeeded" || task.state === "failed";
}

export function BotPluginsPage() {
  const queryClient = useQueryClient();

  const [confirm, setConfirm] = useState<{
    title: string;
    description: string;
    confirmText: string;
    run: () => void;
  } | null>(null);

  const [query, setQuery] = useState("");
  const [source, setSource] = useState<"all" | "amrita" | "nonebot">("all");
  const [page, setPage] = useState(1);
  // 默认折叠当前适配器不支持的插件：通常只挂一个适配器，其余装了也用不上
  const [hideUnsupported, setHideUnsupported] = useState(true);
  const [adapterFilter, setAdapterFilter] = useState("");

  const pluginsQuery = useQuery({
    queryKey: ["bot-plugins"],
    queryFn: () => api.get<PluginListData>("/api/bot/plugins"),
  });

  const tasksQuery = useQuery({
    queryKey: ["plugin-tasks"],
    queryFn: () => api.get<{ tasks: PluginTask[] }>("/api/bot/plugins/tasks"),
    // 有未完成任务时每 2 秒问一次；全部结束就停，不会空转
    refetchInterval: (q) => {
      const list = q.state.data?.data.tasks ?? [];
      return list.some((t) => !isFinished(t)) ? 2000 : false;
    },
    // 失焦不暂停、回窗口补一次：否则切出去等 uv 跑完再回来，看到的还是旧数据
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });

  const storeQuery = useQuery({
    queryKey: [
      "plugin-store",
      query,
      source,
      page,
      hideUnsupported,
      adapterFilter,
    ],
    queryFn: () =>
      api.get<PluginStoreData>(
        `/api/bot/plugins/store?size=${PAGE_SIZE}&page=${page}&source=${source}` +
          (query ? `&q=${encodeURIComponent(query)}` : "") +
          (hideUnsupported ? "&supported_only=true" : "") +
          (adapterFilter
            ? `&adapter=${encodeURIComponent(adapterFilter)}`
            : ""),
      ),
  });

  // plugins 频道：订阅时是任务快照，之后是逐条事件
  const { plugins: wsEvents, connected } = useWs({ channels: ["plugins"] });

  const wsLines = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const ev of wsEvents) {
      if (ev.line === null) continue;
      const list = map.get(ev.task.id);
      if (list) list.push(ev.line);
      else map.set(ev.task.id, [ev.line]);
    }
    return map;
  }, [wsEvents]);

  const tasks = tasksQuery.data?.data.tasks ?? [];
  const latestTask = tasks.length > 0 ? tasks[tasks.length - 1] : undefined;

  // 刷新主路径是 WS 终态事件，轮询只是兜底（mutation 那次拉回来必然是旧的）
  const settledRef = useRef<Set<string>>(new Set());
  const settle = (id: string) => {
    if (settledRef.current.has(id)) return false;
    settledRef.current.add(id);
    return true;
  };

  useEffect(() => {
    let reached = false;
    for (const ev of wsEvents) {
      if (isFinished(ev.task) && settle(ev.task.id)) reached = true;
    }
    if (!reached) return;
    void queryClient.invalidateQueries({ queryKey: ["bot-plugins"] });
    void queryClient.invalidateQueries({ queryKey: ["plugin-store"] });
  }, [wsEvents, queryClient]);

  useEffect(() => {
    if (!latestTask || !isFinished(latestTask)) return;
    if (!settle(latestTask.id)) return;
    void queryClient.invalidateQueries({ queryKey: ["bot-plugins"] });
    void queryClient.invalidateQueries({ queryKey: ["plugin-store"] });
  }, [latestTask, queryClient]);

  // 任务明细兜底：WS 没接上或页面后开时，从任务接口补齐输出
  const detailQuery = useQuery({
    queryKey: ["plugin-task", latestTask?.id],
    queryFn: () =>
      api.get<PluginTask>(`/api/bot/plugins/tasks/${latestTask?.id ?? ""}`),
    enabled: latestTask !== undefined,
    refetchInterval:
      latestTask && !isFinished(latestTask) && !connected ? 2000 : false,
  });

  const liveLines = latestTask ? wsLines.get(latestTask.id) : undefined;
  const taskLines =
    liveLines && liveLines.length > 0
      ? liveLines
      : (detailQuery.data?.data.lines ?? []);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["bot-plugins"] });
    void queryClient.invalidateQueries({ queryKey: ["plugin-tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["plugin-store"] });
  };

  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      api.post<{ task_id?: string; changed?: boolean }>(path, body),
    onSuccess: (res) => {
      toast.success(res.message);
      invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "操作失败");
    },
  });

  const installed = pluginsQuery.data?.data.plugins ?? [];
  const summary = pluginsQuery.data?.data.summary ?? {};
  const store = storeQuery.data?.data.plugins ?? [];
  const storeTotal = storeQuery.data?.data.total ?? 0;
  const hiddenByAdapter = storeQuery.data?.data.hidden_by_adapter ?? 0;
  const storeWarnings = storeQuery.data?.data.warnings ?? [];
  const storeAdapters = storeQuery.data?.data.adapters ?? [];
  const totalPages = Math.max(1, Math.ceil(storeTotal / PAGE_SIZE));

  const runInstall = (entry: PluginStoreEntry) => {
    setConfirm({
      title: `安装 ${entry.name}`,
      description: `安装 ${entry.project_link ?? entry.module_name}，重启后生效。`,
      confirmText: "确认安装",
      run: () =>
        action.mutate({
          path: "/api/bot/plugins/install",
          body: {
            module_name: entry.module_name,
            project_link: entry.project_link,
            version: entry.version,
            target: entry.target,
          },
        }),
    });
  };

  const runUninstall = (entry: PluginEntry) => {
    setConfirm({
      title: `卸载 ${entry.name}`,
      description: `将执行 uv remove 删除 ${entry.project_link ?? entry.module_name}，并从配置移除，重启后不再加载。`,
      confirmText: "确认卸载",
      run: () =>
        action.mutate({
          path: "/api/bot/plugins/uninstall",
          body: {
            module_name: entry.module_name,
            project_link: entry.project_link,
            // 软卸载在「本来就不在配置里」时是空操作，所以卸载一律连包一起删
            purge: true,
          },
        }),
    });
  };

  const installedColumns: Column<PluginEntry>[] = [
    {
      key: "name",
      header: "名称",
      render: (p) => (
        <div className="space-y-0.5">
          <div className="font-medium">{p.name}</div>
          <div className="font-mono text-xs text-muted-foreground">
            {p.module_name}
          </div>
        </div>
      ),
    },
    {
      key: "kind",
      header: "来源",
      render: (p) => (
        <div className="flex flex-wrap gap-1">
          <Badge variant="outline">
            {p.kind ? (KIND_LABEL[p.kind] ?? p.kind) : "—"}
          </Badge>
          {p.is_dependency && <Badge variant="outline">依赖项</Badge>}
        </div>
      ),
    },
    {
      key: "version",
      header: "版本",
      render: (p) => (
        <span className="text-muted-foreground">{p.version ?? "—"}</span>
      ),
    },
    {
      key: "state",
      header: "状态",
      render: (p) => (
        <div className="space-y-1">
          <StateBadge state={p.state} />
          {p.error && (
            <div className="max-w-[22rem] truncate text-xs text-destructive">
              {p.error}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "actions",
      header: "操作",
      render: (p) => {
        // 受保护的插件一律不给操作入口，原因由后端给出
        if (p.protected_reason) {
          return (
            <span className="max-w-[20rem] text-xs text-muted-foreground">
              {p.protected_reason}
            </span>
          );
        }
        // 待生效的两个状态给「撤销」，方向与当初那一步正好相反
        let toggle: { label: string; path: string } | null = null;
        if (p.state === "pending_enable") {
          toggle = { label: "撤销启用", path: "/api/bot/plugins/disable" };
        } else if (p.state === "pending_remove") {
          toggle = { label: "撤销移除", path: "/api/bot/plugins/enable" };
        } else if (p.state === "disabled") {
          toggle = { label: "启用", path: "/api/bot/plugins/enable" };
        } else if (p.state === "running" || p.state === "load_failed") {
          toggle = { label: "禁用", path: "/api/bot/plugins/disable" };
        }

        // 只要环境里真装着这个包就给卸载入口，待生效的两种状态也一样
        return (
          <div className="flex flex-wrap gap-2">
            {toggle && (
              <Button
                size="sm"
                variant="outline"
                disabled={action.isPending}
                onClick={() =>
                  action.mutate({
                    path: toggle.path,
                    body: { module_name: p.module_name },
                  })
                }
              >
                {toggle.label}
              </Button>
            )}
            {p.project_link && (
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive"
                disabled={action.isPending}
                onClick={() => runUninstall(p)}
              >
                卸载
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  const storeColumns: Column<PluginStoreEntry>[] = [
    {
      key: "name",
      header: "名称",
      render: (p) => (
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="font-medium">{p.name}</span>
            {p.is_official && <Badge variant="outline">官方</Badge>}
            <Badge variant="outline">
              {p.source === "amrita" ? "Amrita" : "NoneBot"}
            </Badge>
          </div>
          <div className="font-mono text-xs text-muted-foreground">
            {p.module_name}
          </div>
        </div>
      ),
    },
    {
      key: "desc",
      header: "描述",
      render: (p) => (
        <div className="max-w-[26rem] space-y-0.5">
          <div className="text-sm text-muted-foreground">{p.desc || "—"}</div>
          {p.author && (
            <div className="text-xs text-muted-foreground">by {p.author}</div>
          )}
        </div>
      ),
    },
    {
      key: "adapters",
      header: "适配器",
      render: (p) => (
        <div className="flex max-w-[15rem] flex-wrap gap-1">
          {p.supported_adapters && p.supported_adapters.length > 0 ? (
            p.supported_adapters.map((a) => (
              <Badge key={a} variant="outline">
                {adapterLabel(a)}
              </Badge>
            ))
          ) : (
            <Badge variant="outline">通用</Badge>
          )}
        </div>
      ),
    },
    {
      key: "version",
      header: "版本",
      render: (p) => (
        <span className="text-muted-foreground">{p.version ?? "—"}</span>
      ),
    },
    {
      key: "state",
      header: "状态",
      render: (p) => (
        <div className="space-y-1">
          {p.state ? <StateBadge state={p.state} /> : <span>—</span>}
          {!p.compatible && p.incompatible_reason && (
            <div className="max-w-[18rem] text-xs text-destructive">
              {p.incompatible_reason}
            </div>
          )}
          {!p.supported_by_current && (
            <div className="text-xs text-amber-600 dark:text-amber-400">
              适配器不支持
            </div>
          )}
        </div>
      ),
    },
    {
      key: "actions",
      header: "操作",
      render: (p) => {
        if ((p.state && p.state !== "not_installed") || !p.compatible) {
          return <span className="text-xs text-muted-foreground">—</span>;
        }
        return (
          <Button
            size="sm"
            disabled={action.isPending}
            onClick={() => runInstall(p)}
          >
            安装
          </Button>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">插件管理</h1>

      {latestTask && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Badge className={TASK_CLASS[latestTask.state]}>
                {TASK_LABEL[latestTask.state]}
              </Badge>
              <span>
                {latestTask.action === "install" ? "安装" : "卸载"}{" "}
                {latestTask.package}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs whitespace-pre-wrap">
              {taskLines.length > 0 ? taskLines.join("\n") : "—"}
            </pre>
            {latestTask.error && (
              <p className="text-sm text-destructive">{latestTask.error}</p>
            )}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="installed">
        <TabsList>
          <TabsTrigger value="installed">已安装</TabsTrigger>
          <TabsTrigger value="store">插件商店</TabsTrigger>
        </TabsList>

        <TabsContent value="installed" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-baseline gap-2 text-base">
                {installed.length} 个插件
                {Object.entries(summary).length > 0 && (
                  <span className="text-sm font-normal text-muted-foreground">
                    {Object.entries(summary)
                      .map(([k, v]) => `${STATE_LABEL[k as PluginState]} ${v}`)
                      .join(" · ")}
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable
                columns={installedColumns}
                data={installed as PluginEntry[] & Record<string, unknown>[]}
                loading={pluginsQuery.isLoading}
                emptyText="暂无插件"
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="store" className="space-y-4">
          <Card>
            <CardHeader className="space-y-3">
              <CardTitle className="flex items-baseline gap-2 text-base">
                {storeTotal} 个可用
                {hiddenByAdapter > 0 && (
                  <span className="text-sm font-normal text-muted-foreground">
                    隐藏 {hiddenByAdapter}
                  </span>
                )}
              </CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="max-w-xs"
                  placeholder="搜索插件"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                />
                {(
                  [
                    ["all", "全部"],
                    ["amrita", "Amrita 官方"],
                    ["nonebot", "NoneBot 商店"],
                  ] as const
                ).map(([value, label]) => (
                  <Button
                    key={value}
                    size="sm"
                    variant={source === value ? "default" : "outline"}
                    onClick={() => {
                      setSource(value);
                      setPage(1);
                    }}
                  >
                    {label}
                  </Button>
                ))}
              </div>
              {source !== "amrita" && (
                <p className="text-xs text-muted-foreground">
                  NoneBot
                  商店的插件由第三方发布，非官方维护也不受监管，安装风险自负。
                </p>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Switch
                    checked={hideUnsupported}
                    onCheckedChange={(checked) => {
                      setHideUnsupported(checked);
                      setPage(1);
                    }}
                  />
                  隐藏不支持的
                </label>
                {storeAdapters.length > 1 && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant={adapterFilter === "" ? "default" : "outline"}
                      onClick={() => {
                        setAdapterFilter("");
                        setPage(1);
                      }}
                    >
                      不限适配器
                    </Button>
                    {storeAdapters.map((a) => (
                      <Button
                        key={a.module}
                        size="sm"
                        variant={
                          adapterFilter === a.module ? "default" : "outline"
                        }
                        onClick={() => {
                          setAdapterFilter(a.module);
                          setPage(1);
                        }}
                      >
                        {a.name}
                      </Button>
                    ))}
                  </div>
                )}
              </div>
              {storeWarnings.length > 0 && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  {storeWarnings.join("；")}
                </p>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <DataTable
                columns={storeColumns}
                data={store as PluginStoreEntry[] & Record<string, unknown>[]}
                loading={storeQuery.isLoading}
                emptyText="无匹配结果"
              />
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  第 {page} / {totalPages} 页
                </span>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    上一页
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        title={confirm?.title ?? ""}
        description={confirm?.description ?? ""}
        confirmText={confirm?.confirmText ?? "确认"}
        loading={action.isPending}
        onConfirm={() => {
          confirm?.run();
          setConfirm(null);
        }}
      />
    </div>
  );
}
