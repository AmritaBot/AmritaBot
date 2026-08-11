# AmritaBot - 基于 NoneBot 与 AmritaCore 的 Agent Bot 项目

<p align= "center">
  <img src="./logo/Amrita-nobg.png" width=400 height=400>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/License-AGPL--3.0-orange" alt="License">
  <img src="https://img.shields.io/badge/NoneBot-2.0+-red?logo=nonebot" alt="NoneBot">
</p>

Amrita 是一个基于[NoneBot2](https://nonebot.dev/)与[AmritaCore](https://core.amritabot.com)的强大聊天机器人项目，专为快速构建和部署智能聊天机器人而设计。它是一个完整的 LLM 聊天机器人解决方案，具有强大的功能和灵活性。

## 🌟 特性亮点

- **供应商无关性**: 基于AmritaCore原生开发，原生支持Anthropic/OpenAI/DeepSeek/Gemini等多种厂商。
- **多模态能力**: 支持处理图像等多媒体内容
- **灵活适配**: 原生支持 Onebot-V11 协议，轻松对接 QQ 等平台
- **智能会话管理**: 内置会话控制和历史存储管理
- **插件化架构**: 模块化设计，易于扩展和定制，复用NoneBot2插件系统
- **开箱即用**: 预设丰富的回复模板和功能配置
- **CLI 工具**: 一体化命令行管理工具，简化开发和部署流程
- **Agent**: 支持Agent推理
- **智能上下文管理**: 支持智能Session管理
- **Web UI**: 集成 Web UI，提供可视化管理界面，基于 FastAPI + React 19 + ShadCN UI + TailwindCSS V4 构建。
- **MCP**: 源生MCP Client集成

## 📚 文档和资源

- [官方文档](https://bot.amritabot.com)
- [Core开发文档](https://core.amritabot.com)
- [AmritaSense 开发文档](https://sense.amritabot.com)
- [问题反馈](https://github.com/AmritaBot/Amrita/issues)

## 📦 安装

### 使用模板创建

```bash
# 需要先安装模板：pip install amctl-template-ambot
amctl create -t ambot
```

### 手动安装

```bash
uv add amrita
```

## ⚙️ 环境变量参考

所有配置通过项目根目录的 `.env` 文件（或系统环境变量）注入，NoneBot 启动时自动读取。
以下按来源分类：**Amrita 自定义**（`get_plugin_config` 读取）、**NoneBot 官方**（`get_driver().config` 读取）。

<details>

### Amrita 自定义配置

| 变量                          | 默认值     | 说明                                                                        |
| ----------------------------- | ---------- | --------------------------------------------------------------------------- |
| `LOG_DIR`                     | `logs`     | 日志目录（含 `realtime.jsonl` 实时日志、`event.json` 事件追溯）             |
| `MAX_EVENT_RECORD`            | `1000`     | 事件追溯（event.json）最大记录条数                                          |
| `ADMIN_GROUP`                 | `-1`       | 管理员群组 ID（`-1` 表示未设置；0~10000 的非法值自动重置为 -1）             |
| `AMRITA_LOG_LEVEL`            | `WARNING`  | Amrita 日志级别：`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`                |
| `PUBLIC_GROUP`                | `0`        | 公开群组 ID（Bot 对外展示）                                                 |
| `BOT_NAME`                    | `Amrita`   | 机器人名称                                                                  |
| `RATE_LIMIT`                  | `5`        | 请求速率限制（间隔秒）                                                      |
| `DISABLE_BUILTIN_MENU`        | `false`    | 是否禁用内置菜单                                                            |
| `AUTO_APPROVE_FRIEND_REQUEST` | `true`     | 是否自动通过好友申请                                                        |
| `AUTO_APPROVE_GROUP_REQUEST`  | `true`     | 是否自动通过拉群申请                                                        |
| `USAGE_CHECK_TIME`            | `400`      | 用量统计添加间隔（毫秒）                                                    |
| `NO_AMRITA_FLAG`              | `false`    | 是否禁用 `/amrita` 信息输出                                                 |
| `WEBUI_ENABLE`                | `true`     | 是否启用 WebUI                                                              |
| `WEBUI_USER_NAME`             | `admin`    | WebUI 登录用户名                                                            |
| `WEBUI_PASSWORD`              | `admin123` | WebUI 登录密码（**出厂默认值，使用默认密码时 WebUI 会拒绝访问**，必须修改） |
| `NO_ENV_EDITOR`               | `true`     | 是否禁用 WebUI 的 Dotenv 编辑（**默认禁用防敏感数据泄露**；为 `true` 时页面提示不可用，读写接口均拒绝；需要编辑时设为 `false`） |

### NoneBot 官方配置

| 变量            | 默认值      | 说明                                                                                            |
| --------------- | ----------- | ----------------------------------------------------------------------------------------------- |
| `SUPERUSERS`    | `[]`        | 超级用户列表（JSON 数组，如 `["3196373166"]`），拥有最高权限（LitePerm 管理员、自动清理白名单） |
| `COMMAND_START` | `["/"]`     | 命令起始符（聊天命令前缀、菜单命令解析）                                                        |
| `LOG_LEVEL`     | `INFO`      | NoneBot 日志级别（ORM 等插件跟随）                                                              |
| `ENVIRONMENT`   | `prod`      | 运行环境：`dev`/`prod`                                                                          |
| `DRIVER`        | `~fastapi`  | NoneBot 驱动器（WebUI/API 依赖 FastAPI 驱动）                                                   |
| `HOST`          | `127.0.0.1` | 服务监听地址                                                                                    |
| `PORT`          | `8080`      | 服务监听端口（WebUI 默认使用 `11451`）                                                          |

### 前端开发环境

| 变量                | 默认值                   | 说明                                                  |
| ------------------- | ------------------------ | ----------------------------------------------------- |
| `AMRITA_API_TARGET` | `http://127.0.0.1:11451` | dev server 的 API/WS 代理目标（`bun run dev` 时生效） |

> 提示：`.env` 可通过 WebUI「系统信息 → Dotenv 编辑」在线查看和修改；修改后需重启生效。

</details>

## 🛠️ 开发

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（Python 包管理）
- [Bun](https://bun.sh) 1.x（前端构建）

### 一键开发运行（后端 + 构建前端）

```bash
bash scripts/dev-development.sh
```

依次执行：清理构建产物 -> 构建前端（含类型检查）-> 启动后端（`uv run ambot run`）。

常用参数：

```bash
bash scripts/dev-development.sh --skip-clean       # 跳过清理
bash scripts/dev-development.sh --skip-typecheck   # 构建时跳过类型检查
bash scripts/dev-development.sh --no-restart       # 仅清理 + 构建，不重启后端
```

### 前端开发环境（dev server + 热更新）

```bash
bash scripts/dev-frontend.sh
```

依次执行：清理构建产物 -> 后台启动后端 -> 前台启动前端 dev server（`bun run dev`，
API/WS 自动代理到后端），Ctrl+C 退出时自动停止后端。

### 完整构建（发布）

```bash
bash scripts/full-build.sh
```

依次执行：清理构建产物 -> 构建前端（输出到 `amrita/plugins/webui/service/static/`）-> `uv build` 构建后端包（`dist/` 下生成 wheel + sdist）。

### 其他脚本

```bash
bash scripts/cleanup.sh            # 清理全部构建产物（static/、dist/、build/、egg-info、realtime.jsonl）
bash scripts/cleanup.sh --dry-run  # 预演模式，仅列出将删除的内容
bash scripts/build-frontend.sh     # 仅构建前端（含 typecheck）
```

### 前端开发（Bun dev server）

```bash
cd frontend
bun install
bun run dev   # http://localhost:3000，/api 与 /amrita/ui/ws 代理到后端 11451
```

前端源码位于 `frontend/`（React 19 + TypeScript + ShadCN UI），构建产物输出到 `amrita/plugins/webui/service/static/`（已 gitignore，不提交）。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request 来帮助改进 Amrita！

见[贡献指南](CONTRIBUTING.md)

## 📄 许可证

本项目采用 AGPL-3.0 许可证，详见[LICENSE](LICENSE)文件。
