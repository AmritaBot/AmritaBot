# AmritaBot - 基于 NoneBot 与 AmritaCore 的 Agent Bot 项目

<p align= "center">
  <img src="./logo/Amrita-nobg.png" width=400 height=400>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/License-AGPL--3.0-orange" alt="License">
  <img src="https://img.shields.io/badge/NoneBot-2.0+-red?logo=nonebot" alt="NoneBot">
</p>

Amrita 是一个基于[NoneBot2](https://nonebot.dev/)与[AmritaCore](https://amrita-core.suggar.top)的强大聊天机器人项目，专为快速构建和部署智能聊天机器人而设计。它是一个完整的 LLM 聊天机器人解决方案，具有强大的功能和灵活性。

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

## 🛠️ 开发

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（Python 包管理）
- [Bun](https://bun.sh) 1.x（前端构建）

### 一键开发运行

```bash
bash scripts/devrun.sh
```

依次执行：清理构建产物 → 构建前端（含类型检查）→ 启动后端（`uv run ambot run`）。

常用参数：

```bash
bash scripts/devrun.sh --skip-clean       # 跳过清理
bash scripts/devrun.sh --skip-typecheck   # 构建时跳过类型检查
bash scripts/devrun.sh --no-restart       # 仅清理 + 构建，不重启后端
```

### 完整构建（发布）

```bash
bash scripts/full-build.sh
```

依次执行：清理构建产物 → 构建前端（输出到 `amrita/plugins/webui/service/static/`）→ `uv build` 构建后端包（`dist/` 下生成 wheel + sdist）。

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
