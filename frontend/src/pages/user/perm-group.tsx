import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { PermissionsDetailData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PermissionEditor } from "@/components/shared/PermissionEditor";
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

  const { data, isLoading } = useQuery({
    queryKey: ["perm-group", name],
    queryFn: () =>
      api.get<PermissionsDetailData>(
        `/api/permissions/groups/${encodeURIComponent(name ?? "")}`,
      ),
    enabled: !!name,
  });

  const saveMutation = useMutation({
    mutationFn: (permissions: string) =>
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
        <h1 className="text-2xl font-semibold tracking-tight">
          权限组：{name}
        </h1>
        <p className="text-sm text-muted-foreground">
          已关联权限组：{data.data.permission_groups.join("、") || "无"}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">权限列表</CardTitle>
          <CardDescription>
            每行一条权限：节点路径 + 允许/拒绝开关
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <PermissionEditor
            key={name}
            initial={data.data.permissions}
            onSubmit={(permissions) => saveMutation.mutate(permissions)}
            submitting={saveMutation.isPending}
          />
          <div className="flex justify-start">
            <Button variant="outline" onClick={() => navigate(-1)}>
              返回
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
