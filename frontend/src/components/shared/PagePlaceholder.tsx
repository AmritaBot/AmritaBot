import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** 菜单中有、但前端尚未注册组件的页面 */
export function PagePlaceholder({ name }: { name: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-lg">页面未接入</CardTitle>
          <CardDescription>
            页面「{name}」已在后端注册，但前端尚未实现对应组件。
            请在 <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">src/pages/registry.tsx</code> 中注册。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            第三方插件可通过「后端 on_page + 前端 registry 一行映射」接入 WebUI。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

/** 404 页面 */
export function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-2">
      <p className="text-6xl font-bold text-muted-foreground">404</p>
      <p className="text-muted-foreground">页面不存在</p>
    </div>
  );
}
