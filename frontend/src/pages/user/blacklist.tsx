import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { BlacklistData, BlacklistEntry } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Entry = BlacklistEntry & { kind: "group" | "user" };

export function BlacklistPage() {
  const qc = useQueryClient();
  const [type, setType] = useState<"group" | "user">("group");
  const [id, setId] = useState("");
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["blacklists"],
    queryFn: () => api.get<BlacklistData>("/api/blacklists"),
  });

  const entries: Entry[] = [
    ...(data?.data.groups.map((e) => ({ ...e, kind: "group" as const })) ?? []),
    ...(data?.data.users.map((e) => ({ ...e, kind: "user" as const })) ?? []),
  ];

  const addMutation = useMutation({
    mutationFn: () =>
      api.post(`/api/blacklists/${type}/${encodeURIComponent(id)}`, {
        action: "add",
        reason,
      }),
    onSuccess: (res) => {
      toast.success(res.message);
      setOpen(false);
      setId("");
      setReason("");
      void qc.invalidateQueries({ queryKey: ["blacklists"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const removeMutation = useMutation({
    mutationFn: (entry: Entry) =>
      api.post(`/api/blacklists/${entry.kind}/${encodeURIComponent(entry.id)}`, {
        action: "remove",
      }),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["blacklists"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: Column<Entry>[] = [
    { key: "kind", header: "类型", render: (e) => (e.kind === "group" ? "群组" : "用户") },
    { key: "id", header: "ID", render: (e) => <code className="font-mono text-sm">{e.id}</code> },
    { key: "reason", header: "原因", render: (e) => <span className="text-muted-foreground">{e.reason || "—"}</span> },
    { key: "added_time", header: "拉黑时间", render: (e) => <span className="text-muted-foreground">{e.added_time}</span> },
    {
      key: "actions",
      header: "操作",
      render: (e) => (
        <Button
          variant="destructive"
          size="sm"
          onClick={() => removeMutation.mutate(e)}
          disabled={removeMutation.isPending}
        >
          移除
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">黑名单管理</h1>
          <p className="text-sm text-muted-foreground">
            共 {entries.length} 条（群组 {data?.data.groups.length ?? 0} / 用户 {data?.data.users.length ?? 0}）
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-1 h-4 w-4" />
              添加黑名单
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>添加黑名单</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>类型</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant={type === "group" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setType("group")}
                  >
                    群组
                  </Button>
                  <Button
                    type="button"
                    variant={type === "user" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setType("user")}
                  >
                    用户
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="bl-id">ID</Label>
                <Input
                  id="bl-id"
                  value={id}
                  onChange={(e) => setId(e.target.value)}
                  placeholder={type === "group" ? "群号" : "QQ 号"}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bl-reason">原因</Label>
                <Input
                  id="bl-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="选填"
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                onClick={() => addMutation.mutate()}
                disabled={!id || addMutation.isPending}
              >
                {addMutation.isPending ? "添加中…" : "添加"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">黑名单列表</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={entries}
            loading={isLoading}
            emptyText="黑名单为空"
          />
        </CardContent>
      </Card>
    </div>
  );
}
