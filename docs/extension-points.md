# Amrita 扩展点与事件钩子

面向第三方 NoneBot 插件（以及 Amrita 内置模块）的扩展点清单。
所有钩子都建立在 AmritaSense 的 `EventRegistry` + `MatcherFactory.trigger_event`
之上，AmritaCore 只是在其上做了一层薄封装。

---

## 1. 钩子内核

```python
from amrita_core import on_event  # 底层注册入口
from amrita_core import on_completion  # COMPLETION
from amrita_core import on_precompletion  # BEFORE_COMPLETION
from amrita_core.hook.on import on_preset_fallback  # PRESET_FALLBACK（未从顶层导出）
```

### block 语义（最容易踩的坑）

`Matcher(event_type, priority=10, block=True)`：

- **`block=True`（默认值）表示「我是终点」**：该处理器跑完就结束整条事件链，
  后续优先级的处理器不会执行。
- 观察型钩子必须显式传 `block=False`，否则会静默吃掉别人的钩子。
- `amrita.plugins.chat.events` 里的便捷注册器默认即为 `block=False`。

### 处理器内的控制流

| 调用 | 效果 |
| --- | --- |
| `matcher.pass_event()` | 跳过自己，继续下一个处理器 |
| `matcher.stop_process()` | 终止整条事件链 |

### 参数注入

处理器参数**按类型**匹配（事件对象、`Matcher`、`MessageEvent`、`Bot`），
参数名可自取；带默认值的参数不会参与类型匹配。例如：

```python
@on_precompletion(1, block=False).handle()
async def check(event: PreCompletionEvent, nonebot_event: MessageEvent) -> None: ...
```

---

## 2. Chat 生命周期事件

统一从 `amrita.plugins.chat.events` 导入。

| 事件类型 | 触发时机 | 可变字段 | 能否否决 |
| --- | --- | --- | --- |
| `CHAT_ENTRY` | `entry()` 开头，会话超时检查之前 | — | `event.cancel()` 后 `entry()` 直接返回 |
| `CHAT_REQUEST` | 消息合成与多模态展开后、构建 `CoreChatObject` 前 | `user_input`、`train` | — |
| `CHAT_USAGE_RECORDED` | 用量统计落库后 | — | — |
| `SESSION_COMPACT` | `/session compact` 压缩成功后 | — | — |
| `SEND_MESSAGE` | 最终回复发送前 | `content`（`Message`） | 抛 `NoMessageSendError` 静默拦截 |
| `POKE_SEND_MESSAGE` | 戳一戳回复发送前 | `content` | 抛 `PokeSendError` |
| `CHAT_PANIC_RECOVER` | 工作流解释器 panic 后 | — | `mark_continue()` 让解释器续跑 |

### 示例：改写用户输入

```python
from amrita.plugins.chat.events import ChatRequestEvent, on_chat_request


@on_chat_request()
async def rewrite(event: ChatRequestEvent) -> None:
    event.user_input = f"{event.user_input}\n（请用一句话回答）"
    event.train["content"] += "\n务必简洁。"
```

### 示例：接消息前否决

```python
from amrita.plugins.chat.events import ChatEntryEvent, on_chat_entry


@on_chat_entry()
async def ignore_bots(event: ChatEntryEvent) -> None:
    if event.session_id.startswith("group_") and event.is_group:
        event.cancel()  # 本次不进入 chat 流程，也不回复
```

### 示例：把用量喂给自建计费

`CHAT_USAGE_RECORDED` 是唯一「用量已落库」的挂载点。
Amrita 本身不做计费，`rate` 只在只读 inspect API 中透出，计费逻辑应挂在外部插件：

```python
from amrita.plugins.chat.events import ChatUsageRecordedEvent, on_chat_usage_recorded


@on_chat_usage_recorded()
async def bill(event: ChatUsageRecordedEvent) -> None:
    if event.usage is None:
        return  # provider 未上报，本次只计次
    await my_ledger.add(
        event.session_id,
        event.usage.prompt_tokens,
        event.usage.completion_tokens,
        records=len(event.billing),
    )
```

---

## 3. AmritaCore 事件

| 事件 | 注册器 | 说明 |
| --- | --- | --- |
| `BEFORE_COMPLETION` | `on_precompletion(priority, block)` | 携带 `PreCompletionEvent`，可改上下文消息 |
| `COMPLETION` | `on_completion(priority, block)` | 携带 `CompletionEvent`，可改 `model_response` / `model_reasoning` |
| `PRESET_FALLBACK` | `on_preset_fallback(priority, block)` | 预设调用失败，可切换 `ctx.preset` |

`PreCompletionEvent` / `CompletionEvent` 都提供 `get_context_messages()` /
`get_user_input()` / `get_model_response()`，并支持 `event.message = ...` 回写。

---

## 4. Agent 步骤事件

定义在 `amrita_core.builtins.agent.events`，已由
`amrita.plugins.chat.events` 重导出并配好便捷注册器，无需手写字符串常量。

| 事件类型 | 注册器 | 可变字段 / 控制流 |
| --- | --- | --- |
| `agent.step_intro` | `on_agent_step_intro()` | `override_phase` |
| `agent.step_leave` | `on_agent_step_leave()` | `override_verb`、`override_object` |
| `agent.step_iteration` | `on_agent_step_iteration()` | `end_step`（提前结束本轮） |
| `agent.tool_call` | `on_tool_call()` | `arguments`（改写调用）、`cancel`、抛 `StepAbortError` |
| `agent.tool_return` | `on_tool_return()` | `result`（改写模型看到的内容）、`skip_append`、抛 `StepAbortError` |

### 示例：拦截危险工具调用

```python
from amrita.plugins.chat.events import StepToolCallEvent, on_tool_call


@on_tool_call()
async def guard(event: StepToolCallEvent) -> None:
    if event.tool_name == "shell_exec":
        event.cancel = True  # 调用方会收到 "Cancelled: ..." 而不执行工具
```

---

## 5. 工具注册

全局注册表是 `amrita_core.tools.manager.ToolsManager`（单例）。
插件在 **import 期**注册即可，`chat` 每次会话都会
`clone_tools_manager(ToolsManager())` 克隆全局表，新工具自动进入所有会话：

```python
from amrita_core import simple_tool


@simple_tool
def my_tool(query: str) -> str:
    """工具描述会作为 schema 的 description。"""
    return f"result for {query}"
```

需要自定义执行逻辑（不走框架的 `call_tool`）时用
`@on_tools(schema, custom_run=True, enable_if=lambda: ...)`，
参考 `amrita/plugins/chat/utils/llm_tools/context_tools.py`。

> 注意：chat 会话构建 `DatabackendOptions(skip_mcp_fetch=True)`，
> MCP 工具在 chat 路径上不参与工具池。

---

## 6. 后端替换

`CoreChatObject` 的 `BackendSlots(AbilityBackend, MemoryBackend)`：

| 接口 | 实现 | 作用 |
| --- | --- | --- |
| `AbilityBackend.load_tools` | `NoopAbilityBackend` | 注入工具池（faskill Skills + 全局 ToolsManager） |
| `AbilityBackend.load_presets` | `NoopAbilityBackend` | 提供预设列表 |
| `MemoryBackend.load_memory` | `ChatMemoryBackend` | `LOAD_STATE` 节点 |
| `MemoryBackend.commit_memory` | `ChatMemoryBackend` | `COMMIT_MEMORY` 节点 |

> 这两个后端目前硬编码在 `handlers/chat/__init__.py` 的 `entry()` 里，
> 外部无法在不改源码的情况下替换 —— 需要替换请提 issue。

---

## 7. 配置扩展

`config.extra: dict[str, Any]` 是通用自由字典（`amrita/plugins/chat/config.py`），
插件可把自己的配置放进去，随 Amrita 配置一起持久化。

---

## 8. WebUI 扩展

### 8.1 挂载数据接口

```python
from fastapi import APIRouter
from amrita.plugins.webui.API import register_router

router = APIRouter()


@router.get("/stats")
async def stats() -> dict[str, int]:
    return {"count": 1}


register_router(router, prefix="/api/myplugin", tags=["myplugin"])
```

必须在**插件 import 期**调用：SPA 的 catch-all 路由（`/{full_path:path}`）挂在
`driver.on_startup`，晚于它注册的路由会被抢先匹配而永远返回 `index.html`。
路由受 WebUI 登录中间件保护（`/api` 前缀返回 401 JSON，其他前缀 302 到登录页）。

### 8.2 注册页面（无需重新构建前端）

```python
from amrita.plugins.webui.API import register_page

register_page(
    "/myplugin/dashboard",
    "我的面板",
    category="我的插件",
    icon="activity",
    external_url="/myplugin/page",  # 或者 module_url="/static/plugins/myplugin/page.js"
)
```

前端按以下顺序解析页面组件：

1. 前端内置 `registry`（Amrita 自带页面，需前端构建）
2. `module_url`：运行期 `import()` 的 ESM 模块，取其 `default` 作为组件
3. `external_url`：`<iframe>` 嵌入的独立页面
4. 都没有时渲染占位页

**只要提供 `module_url` 或 `external_url`，第三方插件就无需重新构建前端。**

#### iframe 页面（任何技术栈）

由插件自己的路由提供 HTML 即可，样式与宿主天然隔离。
需要主题/登录态时用 `postMessage` 传递。

#### 运行期 ESM 模块（原生 UI）

模块需 `export default` 一个 React 组件，并把宿主依赖设为 external，
通过 `window.__AMRITA_HOST__` 取用，以保证 React 单实例：

```tsx
const { React } = window.__AMRITA_HOST__!;

export default function Page() {
  const [n, setN] = React.useState(0);
  return React.createElement("button", { onClick: () => setN(n + 1) }, `点击 ${n}`);
}
```

宿主暴露的键：`React`、`ReactDOM`、`ReactDOMClient`、`ReactRouterDOM`。
模块加载失败只影响当前页面（前端有错误边界兜住）。

### 8.3 WebSocket 频道

```python
from amrita.plugins.webui.API import broadcast_ws, register_ws_channel


async def snapshot() -> dict:
    return {"channel": "myplugin", "data": {"ready": True}}


# snapshot 可为同步或异步；返回 None 表示本次无快照
register_ws_channel("myplugin", snapshot)
await broadcast_ws("myplugin", {"ready": False})
```

未声明的频道名会被 `/amrita/ui/ws` 忽略。内置频道为 `system`、`bot`、`logs`。

---

## 9. 当前缺口

- **入口前的消息观察**：`CHAT_ENTRY` 已覆盖「进 chat 前」，但更早的
  `should_respond_with_usage_check`（是否回复判定）仍无钩子。
- **逐 chunk 流式**：`io_stream.set_callback_func` 硬编码为 `ChatStreamSender.handle`，
  外部只能靠 `config.meta` 控制显示，无法观察/改写流式分片。
- **记忆后端替换**：见 §6 的硬编码说明。
- **插件生命周期**：`amrita/utils/plugins.py` 仍是 `# TODO: Amrita plugin system`，
  尚无正式的第三方插件生命周期钩子。
- **前端页面运行时扩展**：`registry.tsx` 仍是编译期常量表；
  `module_url` / `external_url` 是绕过它的两种方式。
