# 维护者文档

面向仓库维护者：发版流程、子模块联动、跨仓库约定。面向使用者的说明放在 README。

## 仓库与子模块

- 主仓库 `AmritaBot`：Python 包与 WebUI 前端
- `website/` → [amrita-docs](https://github.com/AmritaBot/amrita-docs)：文档站源码
- `frontend/packages/ui` → [AmritaBot-UI](https://github.com/AmritaBot/AmritaBot-UI)：宿主与插件共用的 UI 组件包

改动子模块里的代码后，必须在主仓库提交一次指针更新，否则 CI 与发版拿到的还是旧版本。

## WebUI 组件包（`@amrita-constant/ambot-ui`）发布

需要发布新版本的情形：新增或修改了组件、导出了新的类型、插件侧要跟着升级。

前置条件：

- AmritaBot-UI 仓库的 Actions secrets 里有 `NPM_TOKEN`，且该 token 具备 `@amrita` 作用域的发布权限
- npm 上存在 `@amrita` 作用域（组织或用户名占用）

步骤：

1. 在 AmritaBot-UI 改代码，本地 `bun install && bun run typecheck`
2. bump `package.json` 的 `version`（0.x 阶段递增次版本）
3. 提交并推送 `main`
4. 在 GitHub 创建 release，tag 与版本号对齐（如 `v0.1.0`）
5. `publish.yml` 会跑 typecheck 后执行 `npm publish --access public --provenance`
6. 回主仓库更新 `frontend/packages/ui` 子模块指针，提交并推送

契约约定：

- 增删组件导出时同步改 AmritaBot-UI 的 `src/exports.ts`
- 宿主 `HOST_CONTRACT_VERSION` 跟着 bump：只加字段递增次版本位，语义不兼容递增主版本位
- 插件套件 `@amrita/webui-plugin-kit` 的 UI 类型直接取自本包，不要再维护副本

分发形态：

- 当前是源码分发，`exports` 指向 `.ts`，bun 与 vite 可直接消费，纯 Node ESM 不行
- 要支持 Node 侧消费，需要补 tsc 构建产物并把 `exports` 指到 `dist`
