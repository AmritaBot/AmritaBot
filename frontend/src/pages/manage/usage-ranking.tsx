import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquare, Trophy, UserCheck, Users } from "lucide-react";
import { api } from "@/lib/api";
import type { UsageRankingData } from "@/lib/types";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  Skeleton,
  StatCard,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
} from "@amrita-constant/ambot-ui";

const KIND_LABEL: Record<string, string> = {
  group: "群",
  private: "私聊",
  channel: "频道",
};

const WINDOW_OPTIONS = [
  { label: "24 小时", days: 1 },
  { label: "3 天", days: 3 },
  { label: "7 天", days: 7 },
];

type GroupRow = UsageRankingData["groups"][number];
type UserRow = UsageRankingData["users"][number];

/** 消息数占比条：以榜首为 100% */
function ShareBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max((value / max) * 100, 2) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums">
        {value}
      </span>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function RankBadge({ rank }: { rank: number }) {
  if (rank > 3) {
    return (
      <span className="pl-2 font-mono text-xs text-muted-foreground">
        {rank}
      </span>
    );
  }
  return (
    <Badge variant={rank === 1 ? "default" : "secondary"} className="font-mono">
      {rank}
    </Badge>
  );
}

export function UsageRankingPage() {
  const [days, setDays] = useState(3);

  const { data, isLoading } = useQuery({
    queryKey: ["usage-ranking", days],
    queryFn: () =>
      api.get<UsageRankingData>(`/api/usage/ranking?days=${days}&limit=20`),
  });

  const groupColumns: Column<GroupRow>[] = [
    {
      key: "rank",
      header: "#",
      render: (row) => (
        <RankBadge rank={(data?.data.groups.indexOf(row) ?? 0) + 1} />
      ),
    },
    {
      key: "peer",
      header: "会话",
      render: (row) => (
        <div className="flex items-center gap-2">
          <Badge variant="outline">{KIND_LABEL[row.kind] ?? "会话"}</Badge>
          <span className="font-mono text-sm">{row.peer_id}</span>
        </div>
      ),
    },
    {
      key: "messages",
      header: "消息数",
      render: (row) => (
        <ShareBar
          value={row.messages}
          max={data?.data.groups[0]?.messages ?? 0}
        />
      ),
    },
    {
      key: "users",
      header: "活跃成员",
      render: (row) =>
        row.kind === "private" ? (
          <span className="text-sm text-muted-foreground">—</span>
        ) : (
          <span className="text-sm tabular-nums">{row.users}</span>
        ),
    },
    {
      key: "media",
      header: "含图",
      render: (row) => (
        <span className="text-sm tabular-nums text-muted-foreground">
          {row.media_messages}
        </span>
      ),
    },
    {
      key: "last",
      header: "最近活跃",
      render: (row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.last_active ?? "-"}
        </span>
      ),
    },
  ];

  const userColumns: Column<UserRow>[] = [
    {
      key: "rank",
      header: "#",
      render: (row) => (
        <RankBadge rank={(data?.data.users.indexOf(row) ?? 0) + 1} />
      ),
    },
    {
      key: "nick",
      header: "成员",
      render: (row) => (
        <div className="flex flex-col">
          <span className="text-sm">{row.nickname || "（未知昵称）"}</span>
          <span className="font-mono text-xs text-muted-foreground">
            {row.user_id}
          </span>
        </div>
      ),
    },
    {
      key: "messages",
      header: "消息数",
      render: (row) => (
        <ShareBar
          value={row.messages}
          max={data?.data.users[0]?.messages ?? 0}
        />
      ),
    },
    {
      key: "sessions",
      header: "涉及会话",
      render: (row) => (
        <span className="text-sm tabular-nums">{row.sessions}</span>
      ),
    },
    {
      key: "last",
      header: "最近活跃",
      render: (row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.last_active ?? "-"}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">用量排行</h1>
          <p className="text-sm text-muted-foreground">
            按会话与成员统计消息量，数据来自上下文记录
          </p>
        </div>
        <div className="flex gap-1 rounded-lg border p-1">
          {WINDOW_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              type="button"
              onClick={() => setDays(opt.days)}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                days === opt.days
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading || !data ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard
              title="消息总量"
              value={data.data.totals.messages}
              description={`自 ${data.data.window.since.slice(5, 16)}`}
              icon={MessageSquare}
            />
            <StatCard
              title="活跃会话"
              value={data.data.totals.sessions}
              description="有消息记录的会话数"
              icon={Users}
            />
            <StatCard
              title="活跃成员"
              value={data.data.totals.users}
              description="窗口内发过言的 QQ"
              icon={UserCheck}
            />
          </div>

          <Tabs defaultValue="groups">
            <TabsList>
              <TabsTrigger value="groups">群聊 / 会话</TabsTrigger>
              <TabsTrigger value="users">成员</TabsTrigger>
            </TabsList>

            <TabsContent value="groups">
              <Card>
                <CardHeader className="flex flex-row items-center gap-2 pb-3">
                  <Trophy className="h-4 w-4 text-muted-foreground" />
                  <CardTitle className="text-base">会话消息排行</CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable
                    columns={groupColumns}
                    data={data.data.groups}
                    emptyText="窗口内没有记录"
                  />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="users">
              <Card>
                <CardHeader className="flex flex-row items-center gap-2 pb-3">
                  <Trophy className="h-4 w-4 text-muted-foreground" />
                  <CardTitle className="text-base">成员发言排行</CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable
                    columns={userColumns}
                    data={data.data.users}
                    emptyText="窗口内没有记录"
                  />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {data.data.window.ttl_hours !== null &&
            data.data.window.ttl_hours > 0 &&
            days * 24 > data.data.window.ttl_hours && (
              <p className="text-xs text-muted-foreground">
                上下文记录默认只保留 {data.data.window.ttl_hours}{" "}
                小时，更长窗口只能受限于实际留存的记录。
              </p>
            )}
        </>
      )}
    </div>
  );
}
