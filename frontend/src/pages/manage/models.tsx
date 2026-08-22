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
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";

interface ModelRow extends ChatModel {
  __editing?: boolean;
}

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
  // API Key 敏感字段不回传，输入框始终从空开始；
  // apiKeyTouched 记录用户是否修改过，未修改则提交时省略该键（PATCH 语义）
  const [apiKey, setApiKey] = useState("");
  const [apiKeyTouched, setApiKeyTouched] = useState(false);
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

  /** 构建提交 payload：编辑时未修改的 api_key 不提交，避免覆盖已有值 */
  function buildPayload(): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      name,
      model,
      base_url: baseUrl,
      protocol,
      thinking_config: buildThinkingConfig(),
    };
    // 新建：始终提交（可为空）；编辑：仅当用户修改过才提交
    if (!initial || apiKeyTouched) payload.api_key = apiKey;
    return payload;
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
          onChange={(e) => {
            setApiKey(e.target.value);
            setApiKeyTouched(true);
          }}
          placeholder={
            initial?.has_api_key ? "已配置，留空则不修改" : undefined
          }
          type={apiKeyTouched ? "password" : "text"}
        />
        {initial?.has_api_key && !apiKeyTouched && (
          <p className="text-xs text-muted-foreground">
            已配置 API Key。留空并保存将保持原 Key 不变；如需更换请输入新 Key。
          </p>
        )}
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
          onClick={() => onSubmit(buildPayload())}
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
      key: "api_key",
      header: "API Key",
      render: (m) =>
        m.has_api_key ? (
          <Badge variant="secondary">已配置</Badge>
        ) : (
          <Badge variant="outline">未配置</Badge>
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
          {/* default 与普通预设一致，可编辑可删除；仅当删除后预设目录为空时才会自动重建 */}
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setDeleting(m)}
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
              key={editing.name}
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
