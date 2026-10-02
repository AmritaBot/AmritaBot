import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** 菜单中有、但前端尚未注册组件的页面 */
export function PagePlaceholder({ name }: { name: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="text-lg">页面未接入</CardTitle>
          <CardDescription>
            页面「{name}」已在后端注册，但前端没有对应组件， 也未提供{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
              module_url
            </code>{" "}
            或{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
              external_url
            </code>
            。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            第三方插件用后端 <code>register_page</code> 传入{" "}
            <code>module_url</code>（运行期 ESM 模块）或{" "}
            <code>external_url</code>
            （iframe 页面）即可接入 WebUI，<strong>无需重新构建前端</strong>。
            Amrita 自带页面则在{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
              src/pages/registry.tsx
            </code>{" "}
            中登记。
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
