import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { ChatPrompt, ChatPromptsData } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";

type PromptType = "group" | "private";

interface PromptRow extends ChatPrompt {
  type: PromptType;
}

export function PromptsPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<PromptRow | null>(null);
  const [deleting, setDeleting] = useState<PromptRow | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["chat-prompts"],
    queryFn: () => api.get<ChatPromptsData>("/api/chat/prompts"),
  });

  const createMutation = useMutation({
    mutationFn: ({
      type,
      name,
      text,
    }: {
      type: PromptType;
      name: string;
      text: string;
    }) => api.post(`/api/chat/prompts/${type}`, { name, text }),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-prompts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const updateMutation = useMutation({
    mutationFn: ({ row, text }: { row: PromptRow; text: string }) =>
      api.post(
        `/api/chat/prompts/${row.type}/${encodeURIComponent(row.name)}`,
        { text },
      ),
    onSuccess: (res) => {
      toast.success(res.message);
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["chat-prompts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (row: PromptRow) =>
      api.post(
        `/api/chat/prompts/${row.type}/${encodeURIComponent(row.name)}/delete`,
      ),
    onSuccess: (res) => {
      toast.success(res.message);
      // 关闭确认框：删除成功后立即收起（否则对话框残留已删除的条目）
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: ["chat-prompts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-6">
      {/* 删除两步确认 */}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open: boolean) => !open && setDeleting(null)}
        title={`删除提示词「${deleting?.name ?? ""}」？`}
        description={`将删除${deleting?.type === "group" ? "群聊" : "私聊"}提示词，删除后无法恢复，请确认。`}
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleting) deleteMutation.mutate(deleting);
        }}
      />

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">提示词预设</h1>
        <p className="text-sm text-muted-foreground">群聊 / 私聊提示词管理</p>
      </div>

      <Dialog
        open={!!editing}
        onOpenChange={(open: boolean) => !open && setEditing(null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              编辑提示词：{editing?.name}（
              {editing?.type === "group" ? "群聊" : "私聊"}）
            </DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
              <Label>内容</Label>
              <PromptEditor
                key={editing.name + editing.type}
                initial={editing.text}
                onSubmit={(text) =>
                  updateMutation.mutate({ row: editing, text })
                }
                submitting={updateMutation.isPending}
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Tabs defaultValue="group">
        <TabsList>
          <TabsTrigger value="group">群聊提示词</TabsTrigger>
          <TabsTrigger value="private">私聊提示词</TabsTrigger>
        </TabsList>
        <PromptTab
          value="group"
          title="群聊提示词"
          prompts={data?.data.prompts.group ?? []}
          loading={isLoading}
          onCreate={(name, text) =>
            createMutation.mutate({ type: "group", name, text })
          }
          onEdit={setEditing}
          onDelete={setDeleting}
          deletePending={deleteMutation.isPending}
        />
        <PromptTab
          value="private"
          title="私聊提示词"
          prompts={data?.data.prompts.private ?? []}
          loading={isLoading}
          onCreate={(name, text) =>
            createMutation.mutate({ type: "private", name, text })
          }
          onEdit={setEditing}
          onDelete={setDeleting}
          deletePending={deleteMutation.isPending}
        />
      </Tabs>
    </div>
  );
}

/** 单个 tab 版块：提示词列表 + 该类型的新建入口 */
function PromptTab({
  value,
  title,
  prompts,
  loading,
  onCreate,
  onEdit,
  onDelete,
  deletePending,
}: {
  value: PromptType;
  title: string;
  prompts: ChatPrompt[];
  loading: boolean;
  onCreate: (name: string, text: string) => void;
  onEdit: (row: PromptRow) => void;
  onDelete: (row: PromptRow) => void;
  deletePending: boolean;
}) {
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newText, setNewText] = useState("");

  const rows: PromptRow[] = prompts.map((p) => ({ ...p, type: value }));

  const columns: Column<PromptRow>[] = [
    {
      key: "name",
      header: "名称",
      render: (p) => <span className="font-medium">{p.name}</span>,
    },
    {
      key: "text",
      header: "内容",
      render: (p) => (
        <span className="line-clamp-1 max-w-lg text-muted-foreground">
          {p.text}
        </span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      render: (p) => (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => onEdit(p)}>
            编辑
          </Button>
          {p.name !== "default" && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => onDelete(p)}
              disabled={deletePending}
            >
              删除
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <TabsContent value={value}>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle className="text-base">{title}</CardTitle>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-1 h-4 w-4" />
                新建
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>新建{title}</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>名称</Label>
                  <Input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="如：default"
                  />
                </div>
                <div className="space-y-2">
                  <Label>内容</Label>
                  <Textarea
                    value={newText}
                    onChange={(e) => setNewText(e.target.value)}
                    className="h-40 resize-y"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  onClick={() => {
                    onCreate(newName, newText);
                    setCreateOpen(false);
                    setNewName("");
                    setNewText("");
                  }}
                  disabled={!newName}
                >
                  创建
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={rows}
            loading={loading}
            emptyText={`还没有${title}`}
          />
        </CardContent>
      </Card>
    </TabsContent>
  );
}

function PromptEditor({
  initial,
  onSubmit,
  submitting,
}: {
  initial: string;
  onSubmit: (text: string) => void;
  submitting: boolean;
}) {
  const [text, setText] = useState(initial);
  return (
    <div className="space-y-4">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        // 固定高度：长文本在内部滚动，不撑高 Dialog（保存按钮始终可见）
        className="h-72 resize-y"
      />
      <div className="flex justify-end">
        <Button onClick={() => onSubmit(text)} disabled={submitting}>
          {submitting ? "保存中…" : "保存"}
        </Button>
      </div>
    </div>
  );
}
