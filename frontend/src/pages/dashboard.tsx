import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  Bot,
  History,
  MessageSquare,
  Puzzle,
} from "lucide-react";
import {
  ResponsiveContainer,
  Bar,
  BarChart,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { api } from "@/lib/api";
import type { DashboardData } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function DashboardPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardData>("/api/dashboard"),
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }

  const d = data.data;
  const chartData = d.message_stats.labels.map((label, i) => ({
    date: label,
    messages: d.message_stats.data[i] ?? 0,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">仪表盘</h1>
        <p className="text-sm text-muted-foreground">AmritaBot 运行概况</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Bot 状态"
          value={d.bot_connected ? "已连接" : "未连接"}
          icon={Bot}
          description={d.bot_connected ? "OneBot V11 在线" : "等待连接"}
        />
        <StatCard
          title="消息总量"
          value={d.total_message}
          icon={MessageSquare}
        />
        <StatCard
          title="系统健康"
          value={`${d.health}%`}
          icon={Activity}
        />
        <StatCard
          title="已加载插件"
          value={d.loaded_plugins}
          icon={Puzzle}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">消息趋势</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" fontSize={12} stroke="var(--muted-foreground)" />
                  <YAxis fontSize={12} stroke="var(--muted-foreground)" />
                  <Tooltip
                    contentStyle={{
                      background: "var(--card)",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="messages" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">今日收发</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={d.msg_io_status.labels.map((label, i) => ({
                    label,
                    count: d.msg_io_status.data[i] ?? 0,
                  }))}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="label" fontSize={12} stroke="var(--muted-foreground)" />
                  <YAxis fontSize={12} stroke="var(--muted-foreground)" />
                  <Tooltip
                    contentStyle={{
                      background: "var(--card)",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="count" fill="var(--chart-2)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">最近活动</CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/events")}
            className="gap-1 text-xs text-muted-foreground"
          >
            <History className="h-3.5 w-3.5" />
            查看全部
          </Button>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {d.recent_activity.length === 0 && (
              <p className="text-sm text-muted-foreground">暂无活动记录</p>
            )}
            {d.recent_activity.slice(0, 10).map((act, i) => (
              <button
                key={i}
                type="button"
                onClick={() => navigate("/events")}
                className="flex w-full items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-muted/50"
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: act.icon_color }}
                />
                <span className="font-medium">{act.title}</span>
                <span className="flex-1 truncate text-muted-foreground">
                  {act.desc}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {act.time}
                </span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
