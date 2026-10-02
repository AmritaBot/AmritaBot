# 贡献指南

感谢您对 Amrita 项目的兴趣！本指南将帮助您了解如何为项目做出贡献。

## 📋 目录

- [项目概述](#项目概述)
- [技术栈](#技术栈)
- [开发环境设置](#开发环境设置)
- [项目结构](#项目结构)
- [贡献流程](#贡献流程)
- [代码规范](#代码规范)
- [文档规范](#文档规范)
- [社区准则](#社区准则)

## 项目概述

Amrita 是一个基于 [NoneBot2](https://nonebot.dev/) 的强大聊天机器人框架，专为快速构建和部署智能聊天机器人而设计。它不仅是一个 CLI 工具，更是一个完整的 LLM 聊天机器人解决方案，支持多种大语言模型和适配器。

## 技术栈

- **Python 3.10+**
- **[NoneBot2](https://nonebot.dev/)** - 机器人框架
- **FastAPI** - Web 框架（用于 Web UI）
- **Jinja2** - 模板引擎
- **Pydantic** - 数据验证
- **SQLAlchemy** - ORM（通过 `nonebot-plugin-orm`）
- **UV** - 包管理器
- **Ruff** - 代码格式化和 linting

## 开发环境设置

### 1. 克隆项目

```bash
git clone https://github.com/AmritaBot/AmritaBot.git
cd Amrita
```

### 2. 安装依赖

使用 uv（推荐）:

```bash
# 安装开发依赖
uv sync --dev

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate     # Windows
```

或者使用 pip:

```bash
pip install -e ".[full]"
```

### 3. 设置配置文件

复制 `.env` 示例文件并根据需要进行修改：

```bash
cp example/.env.example .env
# 编辑 .env 文件以设置您的配置
```

### 4. 运行项目

```bash
# 创建Bot.py后运行
uv run amrita entry
uv run bot.py

# 使用CLI运行
uv run amrita run
```

## 项目结构

```t
Amrita/
├── amrita/                 # 核心包
│   ├── API.py              # API 接口定义
│   ├── __init__.py         # 包初始化
│   ├── bot.py              # 机器人主入口
│   ├── cli.py              # CLI 命令行工具
│   ├── cmds/               # CLI 命令实现
│   ├── config.py           # 配置定义
│   ├── config_manager.py   # 配置管理器
│   ├── load_test.py        # 负载测试工具
│   ├── plugins/            # 插件系统
│   │   ├── chat/           # 聊天功能
│   │   ├── manager/        # 管理功能
│   │   ├── menu/           # 菜单系统
│   │   ├── perm/           # 权限系统
│   │   └── webui/          # Web UI
│   ├── resource.py         # 资源管理
│   └── utils/              # 通用工具
├── example/                # 示例代码
├── migrations/             # 数据库迁移
├── data/                   # 数据目录
├── logs/                   # 日志目录
├── pyproject.toml          # 项目配置
├── README.md               # 项目说明
└── LICENSE                 # 许可证
```

### 插件系统

Amrita 使用插件化架构，主要插件包括：

- **chat**: 核心聊天功能，支持多种 LLM、会话管理、消息处理
- **manager**: 机器人管理功能，包括自动清理、封禁解封等
- **menu**: 菜单系统，提供命令菜单展示
- **perm**: 权限控制系统，支持细粒度权限节点
- **webui**: Web 可视化界面，提供配置和管理界面

## 贡献流程

### 1. Fork 仓库

在 GitHub 上 Fork 本仓库。

### 2. 创建功能分支

```bash
git checkout -b feature/your-feature-name
# 或
git checkout -b bugfix/your-bug-fix
```

### 3. 开发和测试

编写代码并确保所有测试通过。

### 4. 提交代码

使用约定的提交消息格式：

```bash
git add .
git commit -m "feat: 添加新功能描述"
# 或
git commit -m "fix: 修复问题描述"
```

### 5. 推送分支

```bash
git push origin feature/your-feature-name
```

### 6. 创建 Pull Request

在 GitHub 上创建 Pull Request，描述您的更改和原因。

## 代码规范

### Python 代码规范

- 遵循 PEP 8 编码规范
- 使用 Ruff 进行代码格式化和 linting
- 使用类型提示增强代码可读性
- 函数和类需要包含完整的文档字符串
- 使用中文编写文档字符串

### 提交消息规范

使用约定式提交规范：

- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建工具或辅助工具变动

### 代码质量

- 遵循 DRY（Don't Repeat Yourself）原则
- 编写可测试的代码
- 保持函数和方法的单一职责
- 避免深层嵌套，保持代码简洁

## 文档规范

### 代码注释

- 所有公共 API 必须包含完整的参数说明、返回值说明和异常说明
- 复杂逻辑必须包含简要的实现思路说明
- 使用中文编写文档字符串
- 配置相关代码必须说明配置的作用和使用方式

### 文档更新

- 新功能必须包含相应的文档
- API 变更需要更新文档
- 使用清晰的示例说明功能用法

## 社区准则

### 行为准则

- 尊重所有贡献者和用户
- 提供建设性的反馈
- 保持讨论的技术性
- 避免任何形式的歧视或骚扰

### 问题报告

- 提供详细的环境信息和复现步骤
- 包含错误日志和配置信息（如适用）
- 搜索已存在的问题以避免重复

### 支持请求

- 优先使用 GitHub Issues 进行问题报告
- 提供完整的错误信息和配置
- 尝试提供最小复现示例

## 许可证

本项目采用 [AGPL V3](./LICENSE) 许可证。所有贡献都将遵循此许可证。

## 联系方式

- [GitHub Issues](https://github.com/AmritaBot/AmritaBot/issues)
- 项目文档: `https://amrita.suggar.top`

感谢您的贡献！
