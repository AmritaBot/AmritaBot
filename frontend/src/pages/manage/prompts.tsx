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
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type PromptType = "group" | "private";

interface PromptRow extends ChatPrompt {
  type: PromptType;
}

export function PromptsPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [createType, setCreateType] = useState<PromptType>("group");
  const [editing, setEditing] = useState<PromptRow | null>(null);
  const [newName, setNewName] = useState("");
  const [newText, setNewText] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["chat-prompts"],
    queryFn: () => api.get<ChatPromptsData>("/api/chat/prompts"),
  });

  const rows: PromptRow[] = [
    ...(data?.data.prompts.group.map((p) => ({ ...p, type: "group" as const })) ?? []),
    ...(data?.data.prompts.private.map((p) => ({ ...p, type: "private" as const })) ?? []),
  ];

  const createMutation = useMutation({
    mutationFn: () =>
      api.post(`/api/chat/prompts/${createType}`, { name: newName, text: newText }),
    onSuccess: (res) => {
      toast.success(res.message);
      setCreateOpen(false);
      setNewName("");
      setNewText("");
      void qc.invalidateQueries({ queryKey: ["chat-prompts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const updateMutation = useMutation({
    mutationFn: ({ row, text }: { row: PromptRow; text: string }) =>
      api.post(`/api/chat/prompts/${row.type}/${encodeURIComponent(row.name)}`, { text }),
    onSuccess: (res) => {
      toast.success(res.message);
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["chat-prompts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (row: PromptRow) =>
      api.post(`/api/chat/prompts/${row.type}/${encodeURIComponent(row.name)}/delete`),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-prompts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: Column<PromptRow>[] = [
    { key: "type", header: "类型", render: (p) => (p.type === "group" ? "群聊" : "私聊") },
    { key: "name", header: "名称", render: (p) => <span className="font-medium">{p.name}</span> },
    { key: "text", header: "内容", render: (p) => <span className="line-clamp-1 max-w-lg text-muted-foreground">{p.text}</span> },
    {
      key: "actions",
      header: "操作",
      render: (p) => (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditing(p)}>
            编辑
          </Button>
          {p.name !== "default" && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => deleteMutation.mutate(p)}
              disabled={deleteMutation.isPending}
            >
              删除
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">提示词预设</h1>
          <p className="text-sm text-muted-foreground">群聊 / 私聊提示词管理</p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-1 h-4 w-4" />
              新建提示词
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>新建提示词</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>类型</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant={createType === "group" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setCreateType("group")}
                  >
                    群聊
                  </Button>
                  <Button
                    type="button"
                    variant={createType === "private" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setCreateType("private")}
                  >
                    私聊
                  </Button>
                </div>
              </div>
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
                  className="min-h-[160px]"
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={!newName || createMutation.isPending}
              >
                {createMutation.isPending ? "创建中…" : "创建"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Dialog open={!!editing} onOpenChange={(open: boolean) => !open && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              编辑提示词：{editing?.name}（{editing?.type === "group" ? "群聊" : "私聊"}）
            </DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="space-y-4">
              <Label>内容</Label>
              <PromptEditor
                key={editing.name + editing.type}
                initial={editing.text}
                onSubmit={(text) => updateMutation.mutate({ row: editing, text })}
                submitting={updateMutation.isPending}
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">提示词列表</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={rows}
            loading={isLoading}
            emptyText="还没有提示词"
          />
        </CardContent>
      </Card>
    </div>
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
        className="min-h-[240px]"
      />
      <div className="flex justify-end">
        <Button onClick={() => onSubmit(text)} disabled={submitting}>
          {submitting ? "保存中…" : "保存"}
        </Button>
      </div>
    </div>
  );
}
