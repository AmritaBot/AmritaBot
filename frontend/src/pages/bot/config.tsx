import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { BotConfigData, BotConfigListData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function BotConfigPage() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["bot-config"],
    queryFn: () => api.get<BotConfigListData>("/api/bot/config"),
  });

  // 初次加载：列表接口已返回默认选中文件的完整内容（selected + content），
  // 无需再走一次单文件接口；用户手动点击文件后由 selectFile 接管
  useEffect(() => {
    if (data && data.data.selected && data.data.content) {
      setContent(data.data.content);
    }
  }, [data]);

  const selectFile = (name: string | null) => {
    setSelected(name);
    setContent("");
    if (name) {
      void api
        .get<BotConfigData>(`/api/bot/config/${encodeURIComponent(name)}`)
        .then((res) => setContent(res.data.content))
        .catch((e) => toast.error(e.message));
    }
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      api.post("/api/bot/config", { filename: selected, content }),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["bot-config"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const files = data.data.files;
  const activeFile = selected ?? data.data.selected;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dotenv 编辑</h1>
        <p className="text-sm text-muted-foreground">
          编辑 Bot 环境变量配置文件
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {files.map((f) => (
          <Button
            key={f}
            variant={f === activeFile ? "default" : "outline"}
            size="sm"
            onClick={() => selectFile(f)}
          >
            {f}
          </Button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {activeFile ?? "未选择文件"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            className="min-h-80 font-mono text-sm"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={activeFile ? undefined : "先选择文件"}
            disabled={!activeFile}
            spellCheck={false}
          />
          <div className="flex justify-end">
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={!activeFile || saveMutation.isPending}
            >
              {saveMutation.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
