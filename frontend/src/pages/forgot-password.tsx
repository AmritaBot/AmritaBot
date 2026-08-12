import { useNavigate } from "react-router-dom";
import { ArrowLeft, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

/**
 * 忘记密码页：WebUI 密码由环境变量配置，前端无法自助重置，
 * 本页指导用户通过 .env 环境变量重置密码。
 */
export function ForgotPasswordPage() {
  const navigate = useNavigate();

  return (
    <div className="grid min-h-screen place-items-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
            <KeyRound className="h-7 w-7 text-primary" />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-center">
            <h1 className="text-xl font-semibold tracking-tight">忘记密码</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              WebUI 登录密码由服务器环境变量配置，无法在页面内自助重置。
              请在服务器上按以下步骤修改：
            </p>
          </div>

          <div className="space-y-3 rounded-md bg-muted p-4 text-sm">
            <ol className="list-decimal space-y-2 pl-5 text-muted-foreground">
              <li>
                编辑 Bot 根目录的{" "}
                <code className="rounded bg-background px-1 font-mono text-xs text-primary">
                  .env
                </code>{" "}
                文件（或设置同名环境变量）
              </li>
              <li>
                修改/添加{" "}
                <code className="rounded bg-background px-1 font-mono text-xs text-primary">
                  WEBUI_PASSWORD=你的新密码
                </code>
              </li>
              <li>
                （可选）修改用户名{" "}
                <code className="rounded bg-background px-1 font-mono text-xs text-primary">
                  WEBUI_USER_NAME=你的用户名
                </code>
              </li>
              <li>重启 Amrita（重启后自动生效），返回本页重新登录</li>
            </ol>
            <div className="rounded border border-border bg-background p-3 font-mono text-xs leading-relaxed text-muted-foreground">
              <p>
                <span className="text-muted-foreground/70"># .env 示例</span>
              </p>
              <p>
                <span className="text-primary">WEBUI_USER_NAME</span>=admin
              </p>
              <p>
                <span className="text-primary">WEBUI_PASSWORD</span>
                =your-strong-password
              </p>
            </div>
          </div>

          <p className="text-xs leading-relaxed text-muted-foreground">
            提示：若因登录失败次数过多导致 WebUI 锁定，重启 Amrita 即可解除
            （锁定状态仅存在于内存）。
          </p>

          <Button
            variant="outline"
            className="w-full"
            onClick={() => navigate("/login", { replace: true })}
          >
            <ArrowLeft className="h-4 w-4" />
            返回登录
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
