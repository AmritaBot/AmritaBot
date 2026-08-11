import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Github, HelpCircle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <img
            src="/static/images/logo-96.png"
            alt="AmritaBot"
            className="mx-auto h-16 w-16 rounded-full"
          />
          <CardTitle className="text-xl tracking-tight">
            AmritaBot WebUI
          </CardTitle>
          <CardDescription>登录以管理你的 Bot</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "登录中…" : "登录"}
            </Button>
          </form>
          <div className="flex items-center justify-between pt-1 text-xs text-muted-foreground">
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-foreground"
              onClick={() =>
                window.open(
                  "https://github.com/AmritaBot/AmritaBot#Amrita 自定义配置",
                  "_blank",
                )
              }
            >
              <HelpCircle className="h-3.5 w-3.5" />
              忘记密码？
            </button>
            <a
              href="https://github.com/AmritaBot/AmritaBot"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 hover:text-foreground"
            >
              <Github className="h-3.5 w-3.5" />
              GitHub
            </a>
          </div>
        </CardContent>
      </Card>
      <footer className="absolute bottom-4 text-center text-xs text-muted-foreground">
        © AmritaConstant 2025-{new Date().getFullYear()} · AGPL-3.0
      </footer>
    </div>
  );
}
