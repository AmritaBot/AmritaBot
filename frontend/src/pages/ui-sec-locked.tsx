import { Lock } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

/**
 * 安全锁定页：登录失败次数过多（后端 UI_SEC_LOCKED），所有 API 返回 401 + 锁定标记。
 * 样式与默认密码锁定页一致。
 */
export function UiSecLockedPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10">
            <Lock className="h-7 w-7 text-destructive" />
          </div>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          <h1 className="text-xl font-semibold tracking-tight">
            UI 已安全锁定
          </h1>
          <p className="text-sm text-muted-foreground">
            登录失败次数过多，为保护 Bot 安全已锁定 WebUI，所有访问已被拒绝。
          </p>
          <div className="rounded-md bg-muted p-4 text-left font-mono text-xs leading-relaxed text-muted-foreground">
            <p className="mb-1 font-semibold text-foreground">解除锁定：</p>
            <p>1. 重启 Amrita（锁定状态仅存在于内存）</p>
            <p>2. 使用正确的凭据重新登录</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
