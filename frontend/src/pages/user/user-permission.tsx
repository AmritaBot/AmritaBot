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

/** 用户 / 群组权限编辑页（共用） */
function PermissionScope({
  scope,
  id,
  endpoint,
}: {
  scope: string;
  id: string;
  endpoint: string;
}) {
  const navigate = useNavigate();
  const [permissions, setPermissions] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: [endpoint, id],
    queryFn: () => api.get<PermissionsDetailData>(endpoint),
    enabled: !!id,
  });

  const saveMutation = useMutation({
    mutationFn: () => api.post(endpoint, { permissions }),
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
          {scope}：{id}
        </h1>
        <p className="text-sm text-muted-foreground">
          已关联权限组：{data.data.permission_groups.join("、") || "无"}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">权限字符串</CardTitle>
          <CardDescription>
            每行一条权限，格式如 node.permission
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            className="min-h-60 font-mono text-sm"
            value={permissions || data.data.permissions}
            onChange={(e) => setPermissions(e.target.value)}
            spellCheck={false}
          />
          <div className="flex justify-between">
            <Button variant="outline" onClick={() => navigate(-1)}>
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

export function UserPermissionPage() {
  const { user_id } = useParams<{ user_id: string }>();
  return (
    <PermissionScope
      scope="用户权限"
      id={user_id ?? ""}
      endpoint={`/api/permissions/users/${encodeURIComponent(user_id ?? "")}`}
    />
  );
}

export function GroupPermissionPage() {
  const { group_id } = useParams<{ group_id: string }>();
  return (
    <PermissionScope
      scope="群组权限"
      id={group_id ?? ""}
      endpoint={`/api/permissions/group-scopes/${encodeURIComponent(group_id ?? "")}`}
    />
  );
}

export default GroupPermissionPage;
