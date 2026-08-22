import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw, Save } from "lucide-react";
import { api } from "@/lib/api";
import type { SkillConfig, SkillInfo, SkillsData } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

/** 解析每行一个的文本列表（兼容逗号/换行分隔） */
function parseList(text: string): string[] {
  return text
    .split(/[\n,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function SkillsPage() {
  const qc = useQueryClient();
  const [enable, setEnable] = useState(true);
  const [enabledText, setEnabledText] = useState("");
  const [disabledText, setDisabledText] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["chat-skills"],
    queryFn: () => api.get<SkillsData>("/api/chat/skills"),
  });

  useEffect(() => {
    if (data?.data) {
      setEnable(data.data.config.enable);
      setEnabledText(data.data.config.enabled.join("\n"));
      setDisabledText(data.data.config.disabled.join("\n"));
    }
  }, [data]);

  const reloadMutation = useMutation({
    mutationFn: () => api.post("/api/chat/skills/actions/reload"),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-skills"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const saveMutation = useMutation({
    mutationFn: (cfg: SkillConfig) => api.post("/api/chat/skills", cfg),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-skills"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const save = (cfg: SkillConfig) => saveMutation.mutate(cfg);

  /** 行内启停切换：更新 disabled（白名单模式下启用时同步加入白名单） */
  const toggleSkill = (skill: SkillInfo) => {
    if (!data) return;
    const cfg = data.data.config;
    const disabledSet = new Set(cfg.disabled);
    if (skill.enabled) {
      disabledSet.add(skill.name);
    } else {
      disabledSet.delete(skill.name);
    }
    let enabledList = cfg.enabled;
    if (
      !skill.enabled &&
      enabledList.length > 0 &&
      !enabledList.includes(skill.name)
    ) {
      enabledList = [...enabledList, skill.name];
    }
    save({
      enable: cfg.enable,
      enabled: enabledList,
      disabled: [...disabledSet],
    });
  };

  const columns: Column<SkillInfo>[] = [
    {
      key: "name",
      header: "名称",
      render: (s) => (
        <div className="flex items-center gap-2">
          <span className="font-medium">{s.name}</span>
          {s.version && (
            <span className="text-xs text-muted-foreground">v{s.version}</span>
          )}
        </div>
      ),
    },
    {
      key: "description",
      header: "描述",
      render: (s) => (
        <span className="max-w-md truncate text-sm text-muted-foreground">
          {s.description || "—"}
        </span>
      ),
    },
    {
      key: "status",
      header: "状态",
      render: (s) => {
        if (!s.ok) return <Badge variant="destructive">校验失败</Badge>;
        return s.enabled ? (
          <Badge variant="success">已启用</Badge>
        ) : (
          <Badge variant="secondary">已禁用</Badge>
        );
      },
    },
    {
      key: "path",
      header: "路径",
      render: (s) => <code className="font-mono text-xs">{s.path}</code>,
    },
    {
      key: "actions",
      header: "操作",
      render: (s) => (
        <div className="flex items-center gap-3">
          {!s.ok && s.error && (
            <span
              className="max-w-xs truncate text-xs text-destructive"
              title={s.error}
            >
              {s.error}
            </span>
          )}
          <Button
            variant={s.enabled ? "outline" : "default"}
            size="sm"
            onClick={() => toggleSkill(s)}
            disabled={saveMutation.isPending}
          >
            {s.enabled ? "禁用" : "启用"}
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">技能管理</h1>
          <p className="text-sm text-muted-foreground">
            faskill 技能（config/chat/skills）启停与加载状态
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch
              checked={enable}
              onCheckedChange={(checked) => {
                setEnable(checked);
                if (data) {
                  save({
                    enable: checked,
                    enabled: data.data.config.enabled,
                    disabled: data.data.config.disabled,
                  });
                }
              }}
            />
            <span className="text-sm">技能系统</span>
          </div>
          <Button
            variant="outline"
            onClick={() => reloadMutation.mutate()}
            disabled={reloadMutation.isPending}
          >
            <RefreshCw
              className={`mr-1 h-4 w-4 ${reloadMutation.isPending ? "animate-spin" : ""}`}
            />
            重新加载
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">启停配置</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>启用白名单（每行一个，留空=全部启用）</Label>
              <Textarea
                value={enabledText}
                onChange={(e) => setEnabledText(e.target.value)}
                placeholder="skill_name"
                rows={4}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-2">
              <Label>禁用黑名单（每行一个，优先级高于白名单）</Label>
              <Textarea
                value={disabledText}
                onChange={(e) => setDisabledText(e.target.value)}
                placeholder="skill_name"
                rows={4}
                className="font-mono text-xs"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() =>
                save({
                  enable,
                  enabled: parseList(enabledText),
                  disabled: parseList(disabledText),
                })
              }
              disabled={saveMutation.isPending}
            >
              <Save className="mr-1 h-4 w-4" />
              {saveMutation.isPending ? "保存中…" : "保存配置"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">技能列表</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={data?.data.skills ?? []}
            loading={isLoading}
            emptyText="没有发现技能（请将 SKILL.md 放入 config/chat/skills/）"
          />
        </CardContent>
      </Card>
    </div>
  );
}
