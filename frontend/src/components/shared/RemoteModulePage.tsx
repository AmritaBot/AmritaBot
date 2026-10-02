/**
 * 运行期 ESM 页面：后端注册的页面带 `module_url` 时使用。
 *
 * 首次访问时用 `import()` 拉取模块并渲染其默认导出组件，**无需重新构建前端**。
 * 加载失败只影响当前页面（错误边界兜住），不会拖垮整个 WebUI。
 */

import { Component, Suspense, useMemo, type ReactNode } from "react";
import { loadRemoteComponent } from "@/lib/remote";

class RemoteErrorBoundary extends Component<
  { name: string; children: ReactNode },
  { error: Error | null }
> {
  override state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2">
          <p className="font-semibold">页面「{this.props.name}」加载失败</p>
          <pre className="max-w-2xl overflow-auto rounded bg-muted p-3 text-xs">
            {this.state.error.message}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}

export function RemoteModulePage({ name, url }: { name: string; url: string }) {
  const Page = useMemo(() => loadRemoteComponent(url), [url]);
  return (
    <RemoteErrorBoundary name={name}>
      <Suspense
        fallback={
          <div className="flex min-h-[40vh] items-center justify-center text-sm text-muted-foreground">
            正在加载「{name}」…
          </div>
        }
      >
        <Page />
      </Suspense>
    </RemoteErrorBoundary>
  );
}
