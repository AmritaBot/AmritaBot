import { Github, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

/**
 * 密码锁定页：检测到 WebUI 仍在使用出厂默认密码（admin123）时显示。
 * 此时后端拒绝所有 API 访问，必须配置密码后才能继续使用。
 */
export function PasswordLockedPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10">
            <ShieldAlert className="h-7 w-7 text-destructive" />
          </div>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          <h1 className="text-xl font-semibold tracking-tight">WebUI 已锁定</h1>
          <p className="text-sm text-muted-foreground">
            检测到仍在使用出厂默认密码，为安全起见已拒绝所有访问。
          </p>
          <div className="rounded-md bg-muted p-4 text-left font-mono text-xs leading-relaxed text-muted-foreground">
            <p className="mb-1 font-semibold text-foreground">配置密码步骤：</p>
            <p>
              1. 编辑 Bot 根目录的 <code className="text-primary">.env</code>
            </p>
            <p>
              2. 添加/修改{" "}
              <code className="text-primary">WEBUI_USER_NAME=你的用户名</code>{" "}
              （可选）
            </p>
            <p>
              3. 添加/修改{" "}
              <code className="text-primary">WEBUI_PASSWORD=你的强密码</code>
            </p>
            <p>4. 重启 Amrita 后刷新本页面</p>
          </div>
          <Button
            variant="outline"
            className="w-full"
            onClick={() =>
              window.open(
                "https://github.com/AmritaBot/AmritaBot#web-ui",
                "_blank",
              )
            }
          >
            <Github className="h-4 w-4" />
            查看 GitHub 配置文档
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
