import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { PluginInfo } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function BotPluginsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["bot-plugins"],
    queryFn: () => api.get<{ plugins: PluginInfo[] }>("/api/bot/plugins"),
  });

  const columns: Column<PluginInfo>[] = [
    {
      key: "name",
      header: "名称",
      render: (p) => <span className="font-medium">{p.name}</span>,
    },
    {
      key: "version",
      header: "版本",
      render: (p) => <span className="text-muted-foreground">{p.version}</span>,
    },
    {
      key: "type",
      header: "类型",
      render: (p) => (
        <Badge variant={p.type === "application" ? "default" : "secondary"}>
          {p.type}
        </Badge>
      ),
    },
    {
      key: "description",
      header: "描述",
      render: (p) => (
        <span className="text-muted-foreground">{p.description}</span>
      ),
    },
    {
      key: "is_local",
      header: "来源",
      render: (p) => (
        <Badge variant={p.is_local ? "outline" : "secondary"}>
          {p.is_local ? "本地" : "已安装"}
        </Badge>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">插件管理</h1>
        <p className="text-sm text-muted-foreground">
          已加载的 NoneBot 插件列表
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            已加载 {data?.data.plugins.length ?? 0} 个插件
          </CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={
              (data?.data.plugins ?? []) as PluginInfo[] &
                Record<string, unknown>[]
            }
            loading={isLoading}
            emptyText="没有加载任何插件"
          />
        </CardContent>
      </Card>
    </div>
  );
}
