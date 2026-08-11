import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { PermGroupListData } from "@/lib/types";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function PermissionsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["perm-groups"],
    queryFn: () => api.get<PermGroupListData>("/api/permissions/groups"),
  });

  const createMutation = useMutation({
    mutationFn: () => api.post("/api/permissions/groups", { name }),
    onSuccess: (res) => {
      toast.success(res.message);
      setOpen(false);
      setName("");
      void qc.invalidateQueries({ queryKey: ["perm-groups"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (groupName: string) =>
      api.post(
        `/api/permissions/groups/${encodeURIComponent(groupName)}/delete`,
      ),
    onSuccess: (res) => {
      toast.success(res.message);
      void qc.invalidateQueries({ queryKey: ["perm-groups"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: Column<{ name: string; permissions: string }>[] = [
    {
      key: "name",
      header: "名称",
      render: (g) => <span className="font-medium">{g.name}</span>,
    },
    {
      key: "permissions",
      header: "权限",
      render: (g) => (
        <span className="line-clamp-1 max-w-md font-mono text-xs text-muted-foreground">
          {g.permissions}
        </span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      render: (g) => (
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              navigate(`/permissions/groups/${encodeURIComponent(g.name)}`)
            }
          >
            详情
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => deleteMutation.mutate(g.name)}
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">权限管理</h1>
          <p className="text-sm text-muted-foreground">权限组管理</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-1 h-4 w-4" />
              创建权限组
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>创建权限组</DialogTitle>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="group-name">权限组名称</Label>
              <Input
                id="group-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="如：trusted"
              />
            </div>
            <DialogFooter>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={!name || createMutation.isPending}
              >
                {createMutation.isPending ? "创建中…" : "创建"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">权限组列表</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={data?.data.groups ?? []}
            loading={isLoading}
            emptyText="暂无权限组"
          />
        </CardContent>
      </Card>
    </div>
  );
}
