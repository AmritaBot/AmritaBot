import { useWs } from "@/hooks/use-ws";
import { StatusBadge } from "@/components/shared/DataTable";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function Meter({ label, value }: { label: string; value?: number }) {
  const v = value ?? 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">{value === undefined ? "—" : `${v.toFixed(1)}%`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500"
          style={{ width: `${Math.min(v, 100)}%` }}
        />
      </div>
    </div>
  );
}

export function BotStatusPage() {
  // WS 实时推送：system（资源 2s 间隔）+ bot（连接状态变化）
  const { connected, system, bot } = useWs({ channels: ["system", "bot"] });

  if (!connected) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const status = bot?.status ?? "offline";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bot 状态</h1>
        <p className="text-sm text-muted-foreground">
          运行状态与系统资源用量（WebSocket 实时推送）
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">连接状态</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <StatusBadge status={status} />
          <CardDescription>
            {status === "online" ? "Bot 已连接 OneBot V11" : "Bot 未连接"}
            {connected && " · 实时推送中"}
          </CardDescription>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">系统资源</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Meter label="CPU 使用率" value={system?.cpu_usage} />
          <Meter label="内存使用率" value={system?.memory_usage} />
          <Meter label="磁盘使用率" value={system?.disk_usage} />
          {system?.logical_cores && (
            <p className="text-xs text-muted-foreground">
              逻辑核心：{system.logical_cores}
              {system.network_io && (
                <span className="ml-3">
                  网络：↑ {(system.network_io.sent / 1024 / 1024).toFixed(1)} MB / ↓{" "}
                  {(system.network_io.received / 1024 / 1024).toFixed(1)} MB
                </span>
              )}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
