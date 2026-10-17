# AGENTS.md

给在本仓库工作的 AI 代理（以及新加入的人）看的约定。只写与改动直接相关的硬性要求，风格问题按现有代码对齐。

## 项目概况

- Amrita 是基于 NoneBot2 的 Agent Bot，仓库同时包含 Python 插件层与 React WebUI。
- Python 包在 `amrita/`，插件分 `chat` / `manager` / `webui` 三块，注册在 `pyproject.toml` 的 `[tool.amrita]`。
- `frontend/` 是 WebUI 源码，构建产物输出到 `amrita/plugins/webui/service/static/`。
- `website/` 是文档站子模块，不参与 lint 与 pyright（已在配置里排除）。

## 环境与依赖

- Python 3.10–3.13，包管理只用 uv。
- 改依赖后跑 `uv sync`。不要用 `uv pip install` 或 `pip install` 补装单个包，它们会顺带升级无关依赖，把 `.venv` 搞成和 `uv.lock` 不一致的状态。
- 前端依赖用 bun 安装；`scripts/typecheck.sh` 在 `node_modules` 缺失时会自动 `bun install`。

## 常用命令

- `uv run ruff check .` / `uv run ruff format .`
- `bash scripts/lint.sh --check`：ruff 加 prettier，只检查不改动
- `bash scripts/typecheck.sh`：前端 `tsc --noEmit`
- `bash scripts/check.sh`：CI 入口，pyright + lint + 完整构建；加 `--skip-build` 只跑前两项
- 本地启动：`uv run amrita`，详见 README

## 代码注释风格

- 注释与 docstring 一律中文，单行短句，讲“为什么”和约束，不复述代码本身在做什么。
- 模块顶部 docstring 写职责、关键约束、与其他模块的边界；函数 docstring 写清参数语义与副作用，必要时用 Args/Returns/Raises。
- 分节用 `#  ---- 小节名` 或独立的中文小节注释，前后留空行。
- 待办统一写成 `#  TODO(review #<issue>)：具体动作`，不写“以后优化”这类空话。
- 类型注解必须齐全；pydantic 字段用 `Field(description=...)` 说明含义，描述用中文。
- 不写注释掉的旧代码，不写“新增/修改”这类只在 diff 里有意义的注释。

## WebUI 技术栈

- 后端：FastAPI（`nonebot2[fastapi]`）。路由在 `amrita/plugins/webui/service/route/*.py`，聊天插件自己的接口在 `amrita/plugins/chat/webui/page.py`，前缀 `/api/chat/*`。
- 前端：React 19 + TypeScript + Bun 构建 + Tailwind CSS 4 + shadcn 风格组件 + TanStack Query + react-router-dom 7 + zod + sonner + recharts + lucide 图标。
- 没有 SSR，没有 Jinja2 模板，前端是纯 SPA，构建后由后端托管 `static/`。

## WebUI 布局

- 页面在 `frontend/src/pages`，按域分目录：`dashboard.tsx`、`events.tsx` 等顶层页，`bot/`、`user/`、`manage/`、`system/` 分组。
- 组件分三层：`components/ui` 是 shadcn 原子组件，`components/shared` 是业务通用件（如 `DataTable`），`components/layout` 是框架布局。
- 路由唯一注册点是 `frontend/src/pages/registry.tsx`，key 与后端页面路径一致；未注册的路径渲染占位页。
- 后端侧边栏与页面元数据在 `amrita/plugins/webui/service/sidebar.py` 的 `SideBar` / `RouteRegistry`，插件通过 `register_page` 一类接口注册。
- 请求统一走 `frontend/src/lib/api.ts`：同源 Cookie，响应结构 `{code, message, success, data}`，401 统一跳登录。类型集中在 `frontend/src/lib/types.ts`。

新增一个页面的顺序：写 `pages/` 下的组件 → 在 `registry.tsx` 注册 → 后端注册菜单项 → 补 `lib/types.ts` → 用 `api.get/post` 取数。

## 配置改动

- 配置模型在 `amrita/plugins/chat/config.py`（pydantic + `nonebot_plugin_uniconf`）。新字段必须有中文 `description` 和安全的默认值，默认值要保证旧配置文件行为不变。
- 配置要能在 WebUI 里改时，同步改 `webui/page.py` 的 GET 与 POST，以及前端 `types.ts` 和对应页面。POST 对缺省字段用当前值兜底，避免旧前端只提交部分字段时把新开关重置。

## 测试要求

仓库目前没有 pytest 测试目录，验证以静态检查加手动冒烟为准：

1. `uv run ruff check .`、`uv run ruff format --check .`
2. `uv run pyright`
3. 动了前端就跑 `bash scripts/typecheck.sh`
4. 手动跑一遍改动的命令或接口，并在 PR 里说明验证方式与结果

纯逻辑尽量写成可独立执行的形式，方便用 `python -c` 或临时脚本验证；不要把临时测试脚本提交进仓库。

## Git 与 PR

- 分支名用 `feat/` `fix/` `refactor/` 前缀；提交信息中文，首行说明改了什么，正文写动机与影响面。
- PR 拿到 approval 不等于授权合并；合并默认 squash，等明确指令再动。
