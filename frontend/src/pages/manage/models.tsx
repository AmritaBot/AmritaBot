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
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";

interface ModelRow extends ChatModel {
  __editing?: boolean;
}

const KEY_PLACEHOLDER = "••••••••";

/** 思考模式配置（对应后端 ThinkingConfig） */
const THINKING_EFFORT_OPTIONS = [
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
];
const CONTENT_MODE_OPTIONS = [
  { value: "never", label: "never（剥离全部 reasoning_content）" },
  { value: "by-tool", label: "by-tool（仅工具调用时保留）" },
  { value: "optional", label: "optional（透传）" },
];

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

  // 思考模式配置（ThinkingConfig）
  const tc = initial?.thinking_config ?? {};
  const [thinkingEnabled, setThinkingEnabled] = useState(
    !!tc.thinking_type || !!tc.enable_thinking,
  );
  const [thinkingType, setThinkingType] = useState(
    (tc.thinking_type as string) ?? "",
  );
  const [enableThinking, setEnableThinking] = useState(
    (tc.enable_thinking as boolean) ?? false,
  );
  const [thinkingEffort, setThinkingEffort] = useState(
    (tc.thinking_effort as string) ?? "high",
  );
  const [contentMode, setContentMode] = useState(
    (tc.content_mode as string) ?? "optional",
  );

  /** 收集思考配置：未启用时返回 null（清空） */
  function buildThinkingConfig(): Record<string, unknown> | null {
    if (!thinkingEnabled) return null;
    const cfg: Record<string, unknown> = {
      thinking_effort: thinkingEffort,
      content_mode: contentMode,
    };
    if (thinkingType) cfg.thinking_type = thinkingType;
    cfg.enable_thinking = enableThinking;
    return cfg;
  }

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

      {/* 思考模式配置 */}
      <div className="space-y-3 rounded-md border p-3">
        <div className="flex items-center justify-between">
          <Label className="text-base font-medium">思考模式</Label>
          <Switch
            checked={thinkingEnabled}
            onCheckedChange={setThinkingEnabled}
          />
        </div>
        {thinkingEnabled && (
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>thinking_type（请求属性 thinking.type）</Label>
              <Select value={thinkingType} onValueChange={setThinkingType}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="不设置" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">不设置</SelectItem>
                  <SelectItem value="enabled">enabled</SelectItem>
                  <SelectItem value="disabled">disabled</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between">
              <Label>enable_thinking（请求属性）</Label>
              <Switch
                checked={enableThinking}
                onCheckedChange={setEnableThinking}
              />
            </div>
            <div className="space-y-2">
              <Label>thinking_effort（推理强度）</Label>
              <Select value={thinkingEffort} onValueChange={setThinkingEffort}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {THINKING_EFFORT_OPTIONS.map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>content_mode（reasoning_content 处理）</Label>
              <Select value={contentMode} onValueChange={setContentMode}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONTENT_MODE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
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
              thinking_config: buildThinkingConfig(),
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
  const [deleting, setDeleting] = useState<ChatModel | null>(null);

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
          {/* default 是运行时配置（config.default_preset），不可删除 */}
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setDeleting(m)}
            disabled={deleteMutation.isPending || m.name === "default"}
            title={m.name === "default" ? "默认预设不可删除" : undefined}
          >
            删除
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {/* 删除两步确认 */}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open: boolean) => !open && setDeleting(null)}
        title={`删除模型预设「${deleting?.name ?? ""}」？`}
        description="删除后无法恢复，请确认。"
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleting) deleteMutation.mutate(deleting.name);
        }}
      />
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
