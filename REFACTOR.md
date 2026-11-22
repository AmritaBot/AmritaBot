# AmritaBot V3 重构方案：平台抽象层

文档状态：草案（含已落地部分与后续计划）
适用范围：`amrita/platform/` 及其对业务层的改造

## 1. 背景

AmritaBot 长期建立在 NoneBot2 + OneBot v11 之上，业务代码里随处可见
`nonebot.adapters.onebot.v11` 的事件类型与字段读取：判断群聊靠
`isinstance(GroupMessageEvent)`，取身份靠 `event.user_id`，发消息靠
`MessageSegment`。协议实现的可用性一旦变化（OneBot 侧维护中断即是一例），
这些代码全部要重写。

同时，AmritaBot 的目标形态是 **agentic bot**，而不是通用聊天机器人：

- 它要基于 NoneBot 的事件系统构建自己的数据结构；
- 它需要多平台（QQ 非官方 / QQ 官方 / Telegram / 其他结构近似的 IM）；
- 它要把"消息、媒体、身份、权限"以稳定形状交给 agent，
  而不是让 agent 去理解各家协议。

因此需要一个平台边界层：**协议形状进，amrita 数据结构出**。

## 2. 设计原则

1. **只保证收发与鉴权。** 平台层做三件事：入站归一化、出站发送、身份解析。
   表现形态、平台独有事件、能力对齐，都不属于这一层。
2. **有损转换，保留逃生口。** 归一化必然丢信息，所以原始事件完整保留在 `raw`：
   业务核心不许读它；平台特化插件可以读，甚至可以直接 import 该平台适配器。
3. **platform 是键，adapter 是实现。** QQ 的非官方协议与官方 bot 同属
   `platform="qq"`，会话主键跨实现保持一致。
4. **只提供材料，不做决策。** 给角色但不判定权限；给去重键但不负责去重执行；
   给能力表但不替调用方选降级策略。
5. **字段只增不改。** 新增需求加带默认值的字段，不改既有语义。

## 3. 边界模型

| | agent 系统外 | agent 系统内 |
| --- | --- | --- |
| 事件来源 | NoneBot matcher、适配器回调 | 无（不接触事件） |
| 可用的类型 | NoneBot `Event` / `Bot` | **仅** `Envelope` / `Scope` / `Actor` / `Part` |
| 获取方式 | ingress 预处理、`EnvelopeNBDep`、手动 `envelope_from` | 作为参数传递，或 `current_envelope()` |
| 禁止 | 手工拼 `Envelope` | import 适配器、声明 `Event` 参数、二次转换 |

一句话：边界内不出现"事件"，边界外不出现"归一化之后的假设"。

这条线也解释了为什么不用 AmritaSense 的 `Depends`：Sense 属于 agent 内部管线，
在内部再挂一个"事件 → Envelope"的 provider，等于把边界向内挪一层，
同一个 handler 既能拿到事件又能拿到 Envelope，字段抽取迟早两处不一致。

## 4. 数据模型

```python
Scope(platform: str, kind: "group"|"private"|"channel", id: str, thread: str | None)
Actor(platform, user_id, nickname, role, role_known, is_bot, permissions)
Part(kind, value, meta)          # text / at / reply + 平台原始类型名
Envelope(
    kind, scope, actor, parts, ts, dedupe_key, raw, adapter,
    message_id, reply_to, self_id, edited_ts, provenance, batch_key, action,
)
```

约定：

- `Scope.id` / `Actor.user_id` 一律字符串，禁止在业务层 `int()` 后比较；
- `Part.meta` 是可 JSON 化的 `JsonValue`，要能进日志、进库、跨进程；
- `Envelope.raw` 是 `pydantic.BaseModel | None`（NoneBot 侧事件均为 pydantic 模型）。

## 5. 端口与能力

```python
class Sender(Protocol):
    capabilities: frozenset[str]
    async def send_text(text, *, reply_to=None, thread=None) -> str: ...
    async def send_parts(parts, *, reply_to=None, thread=None) -> str: ...
    async def recall(message_id) -> bool: ...
    async def edit(message_id, parts) -> bool: ...
    async def typing() -> None: ...

class PlatformPort(Protocol):
    name: str        # 平台抽象名，如 "qq"
    adapter: str     # 具体实现名，如 "onebot11" / "milky"
    def match(raw_event, bot=None) -> bool: ...
    def to_envelope(raw_event, bot=None) -> Envelope: ...
    def sender(bot, scope) -> Sender: ...
    async def resolve_role(bot, scope, actor) -> Actor: ...
```

能力表的意义是**如实告知有损**：不在表里的能力，调用即编码错误，而不是被静默模拟。

角色补全的三条语义：

1. **不自动调用**：`ingress` 不查角色，每查一次就是一次平台 API 往返；
2. **不缓存**：避免把临时权限变更钉死在内存里，缓存策略交给调用方；
3. **不猜**：查询失败、平台不支持、字段缺失，一律原样返回 `actor`。

## 6. 转换发生在哪里

- 自动入口：`platform/ingress.py` 的 `event_preprocessor`，早于所有 matcher 与 Sense 管线，
  一次事件只转换一次，结果绑定到 `ContextVar`；
- 系统外取对象：`EnvelopeNBDep`（NoneBot DI）或 `envelope_from(event, bot)`（手动）；
- 系统内取对象：直接收 `Envelope` 参数，或 `current_envelope()`。

## 7. 身份与主键

`uni_id` 是记忆、权限、黑名单的主键，格式与既有实现逐字节一致：

```
QQPlatform_Group_{群号}
QQPlatform_Private_{QQ号}
QQPlatform_Channel_{频道号}
```

`Scope.thread`（Telegram forum topic 之类）**不并入 uni_id**：并进去会让现有记录在
切版当天全部变成孤儿。需要按子区隔离时，显式调用 `identity.thread_uni_id()`。

鉴权只用 `actor`，不用 `provenance`：转发一条管理员的消息，不等于获得管理员权限。

## 8. 平台特化

| 情况 | 做法 |
| --- | --- |
| 多平台共有的语义（文本、图片、@、撤回） | 走平台层 + `Sender` |
| 单一平台独有的能力（戳一戳、合并转发、群精华） | 拆成插件，插件内可硬编码该适配器 |
| 靠形状硬凑的"兼容" | 不做，宁可缺功能 |

平台层因此不保留 poke 这类语义：`Capability` 与 `Sender` 里都没有它，
独有能力由插件在 QQ 适配器上实现。

## 9. 多模态

面向 agentic bot，消息体按"适配器下发什么就下发什么"处理：

- 只做同义归一：`mention` / `mention_all` → `at`；
- 其余保留平台原始类型名（`image` / `record` / `video` / `file` / `face` / `sticker`…）；
- **禁止按用途合并**：语音、视频、文件不压成 `file`，多模态类型本身是信息；
- 未知类型原样保留，`Part.value` 取第一个标量字段，`meta` 保留完整原始段；
- `Envelope.media_parts` 给 agent 侧一个"非文本非寻址"的视图，不做进一步解释。

## 10. 指令层

命令逐步迁移到 alconna，形态固定为"alconna 解参数 + `Envelope` 取环境"：

```python
cmd = on_alconna(
    Alconna("set_leave", Args["target?", str]),
    permission=is_lp_admin,
    default_state=MatcherData(...).model_dump(),   # 菜单读的是 matcher._default_state
)

@cmd.handle()
async def leave(bot: Bot, env: EnvelopeNBDep, target: Match[str]):
    ...
    await cmd.finish(UniMessage.image(raw=btio))   # 发送不再绑具体平台的消息段
```

注意：`on_alconna` 没有 `state` 参数，菜单元数据要用 `default_state`。

## 11. 依赖策略

- `nonebot-adapter-milky`：**可选依赖**（`pip install "amrita[milky]"`）。
  未安装时框架照常启动，QQ 平台下只有 OneBot 实现可用。
  平台层对 milky 采用形状识别 + 延迟 import，不 hard-depend。
- `nonebot-plugin-alconna`：主依赖。命令迁移是既定方向，
  不应让每条命令各自 try-import。

## 12. 迁移策略

按**爆炸半径**排序，而不是按代码量：单文件、单调用点、纯身份读取的先动。

已完成：

| 范围 | 内容 |
| --- | --- |
| 平台层 | `dto` / `ports` / `registry` / `identity` / `shim` / `di` / `ingress` + `qq/{onebot,milky}` |
| 规则 | `chat/check_rule.py`：`is_bot_globally_enabled`、`is_bot_enabled` 改用 `EnvelopeNBDep` |
| 命令 | `manager/leave.py`（alconna + Envelope 双迁移）、`manager/amrita.py`、`manager/status.py` |

后续顺序：

1. `utils/send.py`（`send_forward_msg`）——单向依赖，它一改，`api_stats`、`黑名单`
   等命令即可解锁；
2. 其余 manager 命令（`set_enable`、`clean_groups`、`menu`）；
3. `chat/utils/session_guard.py`、`debounce.py` 等身份类工具；
4. 消息渲染（`synthesize_message` / `format_msg_xml`）——输入契约一改，
   所有提示词拼装都要重新验证，永远最后动；
5. `perm` 层（`is_lp_admin` / `any_has_permission`）；
6. chat 的 8 条命令：与 Sense 的 MatcherSpec 注册方式绑定，
   建议等 platform 层把 chat 的事件读取清理完再动。

## 13. 验证方式

```bash
uv run pytest tests/platform -q                  # 32 passed
uv run pyright amrita/platform                   # 0 error / 0 warning
uv run ruff check amrita/platform tests/platform tests/smoke
uv run python tests/smoke/platform_smoke.py      # 全生命周期冒烟
```

冒烟脚本走完整启动流程（`init()` + `load_plugins()` + `driver._lifespan.startup()`），
再用真实 OneBot 事件验证：入站转换、`Rule` 的 DI 解析、角色按需补全、
命令 handler 的参数解析与出站调用。

类型约束：不用 `object` 做类型标注、不滥用 `Any`、不写 `# type: ignore`；
`cast` 仅用于 `importlib` 取 milky 消息类、以及把框架 `Bot` 基类收窄成具体类型这两处。

## 14. 已踩过的坑

1. **递归类型别名在 pydantic 下炸。** `MetaValue = ... | list["MetaValue"]` 静态检查通过，
   但 pydantic v2 生成 schema 时按隐式递归类型处理，抛 `RecursionError`。
   改用 `pydantic.JsonValue`。跨静态/运行时边界的类型必须两边都过。
2. **不入 startup 就跑冒烟，测出来的失败方式和线上不同。** 未执行
   `driver._lifespan.startup()` 时 `config_manager.ins_config` 尚未注册。
3. **`on_alconna` 没有 `state`。** 菜单元数据必须走 `default_state`。
4. **递归入 uni_id 会让历史失联。** 子区、话题一律走显式 `thread_uni_id()`。
5. **转发来源不能参与鉴权。** 这是 prompt 注入最容易钻的口子。
6. **协议层单点风险仍在。** milky 的协议端标注为 WIP，抽象按能力划、不按字段划；
   平台特有字段不得下沉到业务层。

## 15. 附录：当前实现清单

```
amrita/platform/
├── dto.py        # Scope / Actor / Part / Envelope
├── ports.py      # Sender / PlatformPort / 能力常量 / CapabilityMissing
├── registry.py   # register / get / get_adapter / resolve
├── identity.py   # uni_id / parse_uni_id / thread_uni_id
├── shim.py       # envelope_from / sender_of / role_of / current_envelope
├── di.py         # EnvelopeNBDep / provide_envelope
├── ingress.py    # event_preprocessor：入站唯一转换点
└── qq/
    ├── common.py # 消息段→Part、角色归一化、去重键
    ├── onebot.py # OneBot v11 实现
    └── milky.py  # Milky 实现（形状识别 + 延迟 import）

tests/platform/   # 32 个用例：入站归一化、uni_id 对拍、出站、DI、角色补全、多模态
tests/smoke/      # 全生命周期冒烟脚本
```
