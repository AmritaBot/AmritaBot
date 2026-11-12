# @amrita/webui-plugin-kit

AmritaBot WebUI 的插件构建套件。目标：让外部插件带一份 ESM 模块就能挂进侧栏，不必参与宿主前端构建，也不会打进第二份 React。

## 为什么需要它

宿主用 `import()` 在运行期加载插件模块，同时把 React 等运行时挂在 `window.__AMRITA_HOST__`。但纯 ESM 没有 webpack 那种 `externals`——`import "react"` 会原样留在产物里，浏览器解析失败。手写虚拟模块又容易漏导出（实测踩过：`react/jsx-dev-runtime` 的 `jsxDEV` 不挂在 React 主命名空间上，漏了就是运行期 `o is not a function`）。

套件把这些约定固化下来：导出名从真实的 node_modules 里读取再生成，jsx-runtime 用 `createElement` 现造。

## 用法

插件项目根目录放 `amrita-plugin.json`：

```json
{
  "entry": "src/index.tsx",
  "outdir": "static/plugins/my_plugin",
  "assets": ["src/index.css"]
}
```

然后 `bunx amrita-plugin-build`。或直接在脚本里调：

```ts
import { buildPlugin } from "@amrita/webui-plugin-kit/build";

await buildPlugin({
  entry: "src/index.tsx",
  outdir: "static/plugins/my_plugin",
  assets: ["src/index.css"],
});
```

页面源码照常写，不需要任何特殊写法：

```tsx
import { useEffect, useState } from "react";
import { injectCss, pluginApi } from "@amrita/webui-plugin-kit/runtime";

injectCss(new URL("./index.css", import.meta.url).href, "my-plugin-css");

export default function Page() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    pluginApi.get("/api/myplugin/list").then(setRows);
  }, []);
  return <div className="space-y-4">{/* ... */}</div>;
}
```

后端注册：产物目录随插件包分发，宿主按名字解析 URL 与版本参数。

```python
from pathlib import Path
from amrita.plugins.webui.API import register_page
from amrita.plugins.webui.service.plugin_assets import mount_plugin_assets

# 在插件 import 期挂载产物目录（须早于 driver.on_startup 的 catch-all 路由）
mount_plugin_assets("my_plugin", Path(__file__).parent / "webui")

register_page(
    path="/myplugin/list",
    page_name="我的插件",
    category="系统管理",
    icon="flask-conical",
    module_dir="my_plugin",
)
```

宿主会在导出菜单时拼出 `/plugin-assets/my_plugin/index.js?v=<mtime>`。
mtime 是必需的：`import()` 按 URL 缓存模块，插件重建后不换 URL 浏览器会用旧的。
产物缺失时宿主不给 `module_url`，前端渲染「插件产物不可用」并显示原因，而不是让用户撞 404。

把产物放进宿主的 `static/plugins/<name>/` 也能用（省略 mount 调用即可），
但那是宿主构建产物的目录，`scripts/cleanup.sh` 会清空，只适合本地开发。

## 宿主暴露的依赖

| import | 宿主字段 |
|---|---|
| `react` | `React` |
| `react-dom` | `ReactDOM` |
| `react-dom/client` | `ReactDOMClient` |
| `react/jsx-runtime` / `jsx-dev-runtime` | 由 `React.createElement` 现造 |
| `react-router-dom` | `ReactRouterDOM` |
| `@tanstack/react-query` | `ReactQuery` |
| `lucide-react` | `LucideReact` |

产物末尾会追加 `export const amritaHostContract = N`，宿主加载时比对契约版本，不匹配在控制台点名。

## 样式：最容易踩的坑

宿主 CSS 由宿主的 Tailwind 构建生成，**只包含宿主源码里出现过的类**。实测：

- 能用：`space-y-4`、`rounded-xl`、`bg-card`、`text-muted-foreground`、`font-mono`
- 静默失效：`bg-fuchsia-700`、`ring-8`、`columns-3`、`prose`（宿主从没用过，不会生成）

所以插件只有两条路：

1. 只用宿主已有的设计 token（需要文档和 lint 约束）
2. 自带 CSS，用 `injectCss` / `injectStyleText` 注入

推荐 2 作兜底：不依赖宿主的构建细节，宿主换 Tailwind 版本也不会挂。

## 已知限制

- 插件与宿主同 realm，没有沙箱，能访问宿主上下文。按可信来源对待。
- 宿主 `componentCache` 会永久缓存已加载模块，插件禁用后旧模块仍在内存。
- 入口文件名固定为 `index.js`。自带产物用 `mount_plugin_assets`，
  放进宿主 static/ 的写法请参考上一条说明。
- `module_url` 是 1.10 起的旧接口，仍可用但宿主无法校验可用性；新插件用 `module_dir`。
