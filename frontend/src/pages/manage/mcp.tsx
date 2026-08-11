import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { McpServer, McpServersData } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { StatusBadge } from "@/components/shared/DataTable";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function McpPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<McpServer | null>(null);
  const [newScript, setNewScript] = useState("");
  const [editScript, setEditScript] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["chat-mcp"],
    queryFn: () => api.get<McpServersData>("/api/chat/mcp/servers"),
  });

  const reloadMutation = useMutation({
    mutationFn: () => api.post("/api/chat/mcp/servers/actions/reload"),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-mcp"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.post("/api/chat/mcp/servers", { server_script: newScript }),
    onSuccess: (res) => {
      toast.success(res.message);
      setCreateOpen(false);
      setNewScript("");
      void qc.invalidateQueries({ queryKey: ["chat-mcp"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const updateMutation = useMutation({
    mutationFn: ({ old, newScript }: { old: string; newScript: string }) =>
      api.post(`/api/chat/mcp/servers/${encodeURIComponent(old)}`, {
        server_script: newScript,
      }),
    onSuccess: (res) => {
      toast.success(res.message);
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["chat-mcp"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (script: string) =>
      api.post(`/api/chat/mcp/servers/${encodeURIComponent(script)}/delete`),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-mcp"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: Column<McpServer>[] = [
    {
      key: "server_script",
      header: "脚本路径",
      render: (s) => (
        <code className="font-mono text-xs">{s.server_script}</code>
      ),
    },
    { key: "tools_count", header: "工具数", render: (s) => s.tools_count },
    {
      key: "status",
      header: "状态",
      render: (s) => <StatusBadge status={s.status} />,
    },
    {
      key: "actions",
      header: "操作",
      render: (s) => (
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(s);
              setEditScript(s.server_script);
            }}
          >
            更新
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => deleteMutation.mutate(s.server_script)}
            disabled={deleteMutation.isPending}
          >
            删除
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">MCP 服务器</h1>
          <p className="text-sm text-muted-foreground">Agent MCP 服务器管理</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => reloadMutation.mutate()}
            disabled={reloadMutation.isPending}
          >
            <RefreshCw
              className={`mr-1 h-4 w-4 ${reloadMutation.isPending ? "animate-spin" : ""}`}
            />
            重载全部
          </Button>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-1 h-4 w-4" />
                添加服务器
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>添加 MCP 服务器</DialogTitle>
              </DialogHeader>
              <div className="space-y-2">
                <Label>服务器脚本路径</Label>
                <Input
                  value={newScript}
                  onChange={(e) => setNewScript(e.target.value)}
                  placeholder="/path/to/server.py 或 npx 命令"
                  className="font-mono text-xs"
                />
              </div>
              <DialogFooter>
                <Button
                  onClick={() => createMutation.mutate()}
                  disabled={!newScript || createMutation.isPending}
                >
                  {createMutation.isPending ? "添加中…" : "添加"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Dialog
        open={!!editing}
        onOpenChange={(open: boolean) => !open && setEditing(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>更新 MCP 服务器</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label>原路径</Label>
            <Input
              value={editing?.server_script ?? ""}
              disabled
              className="font-mono text-xs"
            />
            <Label className="pt-2">新路径</Label>
            <Input
              value={editScript}
              onChange={(e) => setEditScript(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
          <DialogFooter>
            <Button
              onClick={() =>
                editing &&
                updateMutation.mutate({
                  old: editing.server_script,
                  newScript: editScript,
                })
              }
              disabled={!editing || !editScript || updateMutation.isPending}
            >
              {updateMutation.isPending ? "更新中…" : "更新"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">服务器列表</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={data?.data.servers ?? []}
            loading={isLoading}
            emptyText="没有配置 MCP 服务器"
          />
        </CardContent>
      </Card>
    </div>
  );
}
