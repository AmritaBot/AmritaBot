import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { DbMetaData } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function InfoGrid({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0)
    return <p className="text-sm text-muted-foreground">无数据</p>;
  return (
    <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 py-0.5 text-sm">
          <span className="text-muted-foreground">{k}</span>
          <span className="truncate font-mono text-xs">{String(v)}</span>
        </div>
      ))}
    </div>
  );
}

function ListCard({
  title,
  rows,
}: {
  title: string;
  rows: Record<string, unknown>[];
}) {
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-1">
          {rows.map((row, i) => (
            <div key={i} className="rounded-md border px-3 py-2 text-sm">
              <InfoGrid data={row} />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function DbMetaPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dbmeta"],
    queryFn: () => api.get<DbMetaData>("/api/dbmeta"),
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const d = data.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">数据库元信息</h1>
        <p className="text-sm text-muted-foreground">
          数据库类型：{d.db_type} · 采集于 {d.collection_timestamp}
        </p>
      </div>

      {d.error && <p className="text-sm text-destructive">{d.error}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">数据库信息</CardTitle>
          </CardHeader>
          <CardContent>
            <InfoGrid data={d.db_info} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">连接统计</CardTitle>
          </CardHeader>
          <CardContent>
            <InfoGrid data={d.connection_stats} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">缓存效率</CardTitle>
          </CardHeader>
          <CardContent>
            <InfoGrid data={d.cache_efficiency} />
          </CardContent>
        </Card>
      </div>

      <ListCard title="表活动" rows={d.table_activity} />
      <ListCard title="索引使用" rows={d.index_usage} />
      <ListCard title="锁信息" rows={d.lock_info} />
      <ListCard title="查询统计" rows={d.query_stats} />
    </div>
  );
}
