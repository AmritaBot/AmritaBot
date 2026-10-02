/**
 * iframe 页面：后端注册的页面带 `external_url` 时使用。
 *
 * 插件可以用任意技术栈写自己的页面（由插件自己的路由提供，或指向外部服务），
 * 再用 `register_page(..., external_url="/myplugin/page")` 声明；
 * **无需重新构建前端**。样式与宿主隔离，主题/登录态需通过 postMessage 传递。
 */

export function ExternalPage({ name, url }: { name: string; url: string }) {
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-2">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">{name}</h1>
        <a
          className="text-xs text-muted-foreground underline underline-offset-2"
          href={url}
          target="_blank"
          rel="noreferrer"
        >
          在新标签页打开
        </a>
      </div>
      <iframe
        title={name}
        src={url}
        className="w-full flex-1 rounded-lg border bg-background"
        referrerPolicy="same-origin"
      />
    </div>
  );
}
