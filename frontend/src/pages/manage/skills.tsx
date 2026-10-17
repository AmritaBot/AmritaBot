import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { SkillConfig, SkillInfo, SkillsData } from "@/lib/types";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

export function SkillsPage() {
  const qc = useQueryClient();
  const [enable, setEnable] = useState(true);
  const [echoDir, setEchoDir] = useState(true);
  const [allowScripts, setAllowScripts] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ["chat-skills"],
    queryFn: () => api.get<SkillsData>("/api/chat/skills"),
  });

  useEffect(() => {
    if (data?.data) {
      setEnable(data.data.config.enable);
      setEchoDir(data.data.config.echo_skill_directory);
      setAllowScripts(data.data.config.allow_script_execution);
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
    mutationFn: (cfg: Partial<SkillConfig>) =>
      api.post("/api/chat/skills", cfg),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["chat-skills"] });
    },
    onError: (e: Error) => {
      toast.error(e.message);
      // 保存失败时以服务端为准，避免开关停留在未落盘的状态
      void qc.invalidateQueries({ queryKey: ["chat-skills"] });
    },
  });

  /** 保存：只提交变更字段，其余由后端沿用当前配置（避免并发与未加载时覆盖） */
  const save = (patch: Partial<SkillConfig>) => saveMutation.mutate(patch);

  /** 行内启停切换：维护 selected 列表（空=全部启用；非空=仅列表内启用） */
  const toggleSkill = (skill: SkillInfo) => {
    if (!data) return;
    const cfg = data.data.config;
    const allNames = data.data.skills.map((s) => s.name);
    let selected = cfg.selected;
    if (skill.enabled) {
      // 禁用：selected 为空时需显式列出其余全部技能；非空时从中移除
      const others = allNames.filter((n) => n !== skill.name);
      selected =
        selected.length === 0
          ? others
          : selected.filter((n) => n !== skill.name);
    } else if (selected.length === 0) {
      // 全启用状态下无需修改（所有技能均已启用）
      return;
    } else {
      // 启用：非空 selected 中加入该技能
      selected = [...selected, skill.name];
    }
    save({ enable: cfg.enable, selected });
  };

  const columns: Column<SkillInfo>[] = [
    {
      key: "enabled",
      header: "启用",
      render: (s) => (
        <Switch
          checked={s.enabled}
          onCheckedChange={() => toggleSkill(s)}
          disabled={!s.ok || saveMutation.isPending}
          aria-label={`${s.enabled ? "禁用" : "启用"}技能 ${s.name}`}
        />
      ),
    },
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
      header: "",
      render: (s) =>
        !s.ok && s.error ? (
          <span
            className="max-w-xs truncate text-xs text-destructive"
            title={s.error}
          >
            {s.error}
          </span>
        ) : null,
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
                    selected: data.data.config.selected,
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
          <CardTitle className="text-base">执行策略</CardTitle>
          <p className="text-sm text-muted-foreground">
            影响技能被调用时的返回内容与脚本工具注入。
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="text-sm font-medium">回显技能目录</div>
              <p className="text-xs text-muted-foreground">
                返回内容开头附带技能所在目录；远程沙箱场景建议关闭。
              </p>
            </div>
            <Switch
              checked={echoDir}
              onCheckedChange={(checked) => {
                setEchoDir(checked);
                save({ echo_skill_directory: checked });
              }}
              disabled={saveMutation.isPending || !data}
              aria-label="回显技能目录"
            />
          </div>
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="text-sm font-medium">允许执行技能脚本</div>
              <p className="text-xs text-muted-foreground">
                关闭后不再注入脚本工具，技能只返回正文；与目录回显相互独立。
              </p>
            </div>
            <Switch
              checked={allowScripts}
              onCheckedChange={(checked) => {
                setAllowScripts(checked);
                save({ allow_script_execution: checked });
              }}
              disabled={saveMutation.isPending || !data}
              aria-label="允许执行技能脚本"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">技能列表</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => save({ enable, selected: [] })}
              disabled={saveMutation.isPending}
              title="清空 selected 列表，恢复全部技能启用"
            >
              全部启用
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            勾选开关 = 启用对应技能；清空启用名单（点击“全部启用”）即全部启用。
          </p>
          <p className="text-xs text-muted-foreground/80">
            （您也可以在配置文件处修改）
          </p>
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
