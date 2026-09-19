# AmritaBot WebUI

AmritaBot 的 Web 管理界面（前端）。构建产物输出到 `amrita/plugins/webui/service/static/`，
由后端 FastAPI 以 `/static` 路径托管，随 Python 包一起分发。

## 技术栈

| 领域                       | 选型                                                          |
| -------------------------- | ------------------------------------------------------------- |
| 运行时 / 构建 / 开发服务器 | [Bun](https://bun.com)（`Bun.build` + `bun-plugin-tailwind`） |
| UI 框架                    | React 19（`react-jsx`）                                       |
| 样式                       | Tailwind CSS v4 + `tw-animate-css`                            |
| 组件                       | shadcn/ui（new-york）+ Radix UI + `lucide-react`              |
| 路由                       | react-router v7（data router，支持 `useBlocker`）             |
| 数据请求                   | TanStack Query v5 + 统一 `api` 客户端                         |
| 表单 / 校验                | react-hook-form + zod                                         |
| 图表 / 拖拽 / 提示         | recharts、@dnd-kit、sonner                                    |

## 目录结构

```
frontend/
├── build.ts              # 构建脚本（Bun.build 驱动，含产物修补逻辑）
├── bunfig.toml           # Bun 静态服务插件（bun-plugin-tailwind）
├── components.json       # shadcn/ui 配置（指向 styles/globals.css）
├── styles/globals.css    # Tailwind 主题变量与 @theme 映射
└── src/
    ├── index.html        # HTML 入口
    ├── index.ts          # 开发服务器（静态托管 + /api 代理 + WS 桥接）
    ├── index.css         # CSS 入口（import globals.css + @layer base）
    ├── frontend.tsx      # React 入口（QueryClient / Router / AuthProvider）
    ├── App.tsx           # 应用外壳、鉴权与安全锁分流、菜单路由生成
    ├── components/       # layout / shared / ui（shadcn 组件）
    ├── hooks/            # use-auth、use-theme、use-ws
    ├── lib/              # api 客户端、类型、菜单与路由工具
    └── pages/            # 页面（dashboard、events、manage、system、user …）
```

路径别名 `@/*` → `src/*`（见 `tsconfig.json`）。

## 开发

推荐使用顶层脚本（会自动清理产物、后台拉起后端、前台起前端 dev server）：

```bash
bash ../scripts/dev-frontend.sh
```

也可以只跑前端：

```bash
bun install
bun run dev          # dev server: http://localhost:3000
```

dev server 由 `src/index.ts` 提供：

- 静态资源与 `.tsx` / `.css` 按需编译（走 `bun-plugin-tailwind` 管道）
- `/api/*` 代理到后端（默认 `http://127.0.0.1:11451`，可用 `AMRITA_API_TARGET` 覆盖）
- `/amrita/ui/ws` 浏览器 ⇄ 后端 WebSocket 双向桥接（透传 cookie 与关闭码）

## 构建

```bash
bun run build              # 产物 -> ../amrita/plugins/webui/service/static/
bun run build:local        # 产物 -> frontend/dist/（本地预览用）
bash ../scripts/build-frontend.sh        # 顶层入口，含 typecheck
bash ../scripts/build-frontend.sh --skip-typecheck
```

`bun run build` 通过 `build.ts` 调用 `Bun.build`，其中包含针对 Bun 版本差异的产物修补
（`index.html` 的 script 指向、favicon 注入），以及保留 `static/images/` 静态资源。
完整构建（前端 + `uv build`）请用 `bash ../scripts/full-build.sh`。

## 代码检查

```bash
bun run typecheck          # tsc --noEmit
bun run lint               # 调用 ../scripts/lint.sh（ruff + prettier，会格式化）
bun run lint:check         # 只检查不修改
```

CSS 不在 lint 里单独校验：它由构建链路的 `bun-plugin-tailwind` 编译，语法错误会在
`bun run build` 时直接报错。

## 样式约定

- `styles/globals.css`：`@import "tailwindcss"`、`@custom-variant dark`、`@theme inline`
  把 CSS 变量映射成 Tailwind 颜色/圆角 token（AmritaSense 主题）。
- `src/index.css`：CSS 入口，负责 `@import "../styles/globals.css"` 与全局 `@layer base`。
- Tailwind v4 自动扫描源码，**没有** `tailwind.config.js`，也不需要 content 配置；
  改主题请在 `styles/globals.css` 里改 CSS 变量。
- 新增 shadcn 组件用 `bunx shadcn@latest add <name>`，它会读取 `components.json`。
