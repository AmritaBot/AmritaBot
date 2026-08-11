import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  Area,
  AreaChart,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { api } from "@/lib/api";
import type { ChatInsightsData } from "@/lib/types";
import { StatCard } from "@/components/shared/StatCard";
import { Skeleton } from "@/components/ui/skeleton";
import { Coins, Gauge, MessageSquare } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function InsightsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["chat-insights"],
    queryFn: () => api.get<ChatInsightsData>("/api/chat/insights"),
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
  const chartData = d.chart_data.map((row) => ({
    date: row.date,
    input: row.token_input,
    output: row.token_output,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">信息统计</h1>
        <p className="text-sm text-muted-foreground">Token 用量与调用统计</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard title="输入 Token" value={d.token_prompt} icon={Coins} />
        <StatCard title="输出 Token" value={d.token_completion} icon={Coins} />
        <StatCard title="调用次数" value={d.usage_count} icon={MessageSquare} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Token 趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="inputGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="5%"
                      stopColor="var(--chart-1)"
                      stopOpacity={0.4}
                    />
                    <stop
                      offset="95%"
                      stopColor="var(--chart-1)"
                      stopOpacity={0}
                    />
                  </linearGradient>
                  <linearGradient id="outputGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="5%"
                      stopColor="var(--chart-3)"
                      stopOpacity={0.4}
                    />
                    <stop
                      offset="95%"
                      stopColor="var(--chart-3)"
                      stopOpacity={0}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="date"
                  fontSize={12}
                  stroke="var(--muted-foreground)"
                />
                <YAxis fontSize={12} stroke="var(--muted-foreground)" />
                <Tooltip
                  contentStyle={{
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="input"
                  name="输入"
                  stroke="var(--chart-1)"
                  fill="url(#inputGrad)"
                />
                <Area
                  type="monotone"
                  dataKey="output"
                  name="输出"
                  stroke="var(--chart-3)"
                  fill="url(#outputGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
