import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { PermissionsDetailData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function PermGroupDetailPage() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [permissions, setPermissions] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["perm-group", name],
    queryFn: () => api.get<PermissionsDetailData>(`/api/permissions/groups/${encodeURIComponent(name ?? "")}`),
    enabled: !!name,
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      api.post(`/api/permissions/groups/${encodeURIComponent(name ?? "")}`, {
        permissions,
      }),
    onSuccess: (res) => toast.success(res.message),
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">权限组：{name}</h1>
        <p className="text-sm text-muted-foreground">
          已关联权限组：{data.data.permission_groups.join("、") || "无"}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">权限字符串</CardTitle>
          <CardDescription>每行一条权限，格式如 node.permission</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            className="min-h-[240px] font-mono text-sm"
            value={permissions || data.data.permissions}
            onChange={(e) => setPermissions(e.target.value)}
            spellCheck={false}
          />
          <div className="flex justify-between">
            <Button variant="outline" onClick={() => navigate("/permissions/groups")}>
              返回
            </Button>
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
