import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { ChatModel, ChatModelsData } from "@/lib/types";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ModelRow extends ChatModel {
  __editing?: boolean;
}

const KEY_PLACEHOLDER = "••••••••";

function ModelForm({
  initial,
  onSubmit,
  submitting,
}: {
  initial?: ChatModel | null;
  onSubmit: (data: Record<string, unknown>) => void;
  submitting: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [model, setModel] = useState(initial?.model ?? "");
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? "");
  const [apiKey, setApiKey] = useState(
    initial && initial.api_key !== KEY_PLACEHOLDER ? initial.api_key : "",
  );
  const [protocol, setProtocol] = useState(initial?.protocol ?? "__main__");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>名称</Label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={!!initial}
        />
      </div>
      <div className="space-y-2">
        <Label>模型标识</Label>
        <Input value={model} onChange={(e) => setModel(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label>Base URL</Label>
        <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label>API Key</Label>
        <Input
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={initial ? KEY_PLACEHOLDER : undefined}
        />
      </div>
      <div className="space-y-2">
        <Label>协议</Label>
        <Input value={protocol} onChange={(e) => setProtocol(e.target.value)} />
      </div>
      <DialogFooter>
        <Button
          onClick={() =>
            onSubmit({
              name,
              model,
              base_url: baseUrl,
              api_key: apiKey,
              protocol,
            })
          }
          disabled={!name || !model || submitting}
        >
          {submitting ? "保存中…" : "保存"}
        </Button>
      </DialogFooter>
    </div>
  );
}

export function ModelsPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ChatModel | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["chat-models"],
    queryFn: () => api.get<ChatModelsData>("/api/chat/models"),
  });

  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post("/api/chat/models", payload),
    onSuccess: (res) => {
      toast.success(res.message);
      setCreateOpen(false);
      void qc.invalidateQueries({ queryKey: ["chat-models"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      name,
      payload,
    }: {
      name: string;
      payload: Record<string, unknown>;
    }) => api.post(`/api/chat/models/${encodeURIComponent(name)}`, payload),
    onSuccess: (res) => {
      toast.success(res.message);
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["chat-models"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) =>
      api.post(`/api/chat/models/${encodeURIComponent(name)}/delete`),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-models"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: Column<ModelRow>[] = [
    {
      key: "name",
      header: "名称",
      render: (m) => <span className="font-medium">{m.name}</span>,
    },
    {
      key: "model",
      header: "模型",
      render: (m) => <code className="font-mono text-xs">{m.model}</code>,
    },
    {
      key: "base_url",
      header: "Base URL",
      render: (m) => (
        <span className="text-muted-foreground">{m.base_url}</span>
      ),
    },
    {
      key: "protocol",
      header: "协议",
      render: (m) => (
        <span className="text-xs text-muted-foreground">{m.protocol}</span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      render: (m) => (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditing(m)}>
            编辑
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => deleteMutation.mutate(m.name)}
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
          <h1 className="text-2xl font-semibold tracking-tight">模型预设</h1>
          <p className="text-sm text-muted-foreground">管理可用的模型配置</p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-1 h-4 w-4" />
              新建模型
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>新建模型预设</DialogTitle>
            </DialogHeader>
            <ModelForm
              onSubmit={(payload) => createMutation.mutate(payload)}
              submitting={createMutation.isPending}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Dialog
        open={!!editing}
        onOpenChange={(open: boolean) => !open && setEditing(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑模型：{editing?.name}</DialogTitle>
          </DialogHeader>
          {editing && (
            <ModelForm
              initial={editing}
              onSubmit={(payload) =>
                updateMutation.mutate({ name: editing.name, payload })
              }
              submitting={updateMutation.isPending}
            />
          )}
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">模型列表</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={(data?.data.models ?? []) as ModelRow[]}
            loading={isLoading}
            emptyText="还没有模型预设"
          />
        </CardContent>
      </Card>
    </div>
  );
}
