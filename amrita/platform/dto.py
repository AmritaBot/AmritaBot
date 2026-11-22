"""平台无关的数据传输对象（DTO）。

业务层只允许依赖本模块与 :mod:`amrita.platform.ports`，不允许 import 任何具体适配器。
所有对象 frozen + slots，可直接序列化进日志、推送或数据库。

设计口径（见 REFACTOR.md 第 5、13 节）：

* platform 层只保证**收发**与**鉴权**，其余语义下放给特化插件；
* 转换必定有损，所以 ``raw`` 完整保留，作为逃生口；
* 消息体不按用途合并，适配器下发什么就下发什么。

字段全部带默认值，新增字段只增不改（加字段不算破坏）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from pydantic import BaseModel, JsonValue

# meta 值必须可 JSON 化：用 pydantic JsonValue，手写递归别名会让 pydantic v2 抛 RecursionError。
MetaScalar: TypeAlias = str | int | float | bool | None
MetaValue: TypeAlias = JsonValue

# 事件大类
MESSAGE = "message"
EDIT = "edit"  # 编辑：同一 message_id 的内容变更，跨平台通用语义
NOTICE = "notice"  # 成员变动、撤回、置顶等
REQUEST = "request"  # 加好友 / 入群申请
ACTION = "action"  # 用户动作：按钮回调、内联查询选择（不是消息）
META = "meta"
UNKNOWN = "unknown"
EVENT_KINDS = frozenset({MESSAGE, EDIT, NOTICE, REQUEST, ACTION, META, UNKNOWN})

# 会话类别：channel 为单向广播（Telegram channel / QQ 频道）
GROUP = "group"
PRIVATE = "private"
CHANNEL = "channel"
SCOPE_KINDS = frozenset({GROUP, PRIVATE, CHANNEL})

# 角色：与平台的具体枚举解耦，映射在入站层完成
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_SYSTEM = "system"
ROLES = frozenset({ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER, ROLE_SYSTEM})

# 权限位：只在平台能明确给出时填充，缺省为空集（不做推断）
PERM_SEND_MESSAGES = "send_messages"
PERM_MANAGE_MESSAGES = "manage_messages"
PERM_MANAGE_CHAT = "manage_chat"
PERM_RESTRICTED = "restricted"  # 被限制发言等


@dataclass(frozen=True, slots=True)
class Scope:
    """一次交互发生的"地点"。

    ``platform`` 是平台抽象名（QQ 系统一为 ``"qq"``），不是适配器名。
    ``thread`` 承接 Telegram forum topic / 频道子区这类二级会话；
    它不参与 uni_id（避免历史记录被无声拆分），需要时用
    :func:`amrita.platform.identity.thread_uni_id` 显式分桶。
    """

    platform: str
    kind: str
    id: str
    thread: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id))
        if self.thread is not None:
            object.__setattr__(self, "thread", str(self.thread))
        if self.kind not in SCOPE_KINDS:
            raise ValueError(f"unsupported scope kind: {self.kind!r}")
        if not self.platform:
            raise ValueError("scope.platform must not be empty")

    @property
    def is_group(self) -> bool:
        return self.kind in (GROUP, CHANNEL)

    def __str__(self) -> str:
        base = f"{self.platform}:{self.kind}:{self.id}"
        return f"{base}#{self.thread}" if self.thread else base


@dataclass(frozen=True, slots=True)
class Actor:
    """行为主体。

    ``role`` 是归一化后的角色，业务层只读；平台能给出的细粒度权限放在
    ``permissions``，缺省为空集——空集表示"未提供"，不表示"没有权限"。
    """

    platform: str
    user_id: str
    nickname: str | None = None
    role: str = ROLE_MEMBER
    role_known: bool = False  # 事件里是否真的带了角色；False 只表示"未提供"
    is_bot: bool = False
    permissions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", str(self.user_id))
        if self.role not in ROLES:
            # 平台没有提供角色时按最小权限处理，绝不向上猜。
            object.__setattr__(self, "role", ROLE_MEMBER)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(frozen=True, slots=True)
class Part:
    """消息体的一个片段。

    ``kind`` 只对 text / at / reply 做同义归一，其余保留适配器原始类型名
    （image / record / video / file / face / sticker / document / voice …）。

    约定用于的 ``meta`` 键（有就填，没有不补）：

    * 媒体：``file_id`` / ``file_unique_id`` / ``mime`` / ``size`` / ``name``
      / ``duration`` / ``width`` / ``height``
    * 文本：``entities``（富文本实体，含 offset/length/type/url）
    * 引用：``reply_to``（被引用消息 id）
    * 原始：``type`` / ``data``（适配器原始段，始终保留）
    """

    kind: str
    value: str
    meta: Mapping[str, MetaValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Envelope:
    """归一化后的入站事件。"""

    kind: str
    scope: Scope
    actor: Actor
    parts: tuple[Part, ...] = ()
    ts: float = 0.0
    dedupe_key: str = ""
    raw: BaseModel | None = None  # 平台原始事件（nonebot 侧均为 pydantic 模型）
    adapter: str = ""

    # 回复链与身份
    message_id: str = ""  # 平台消息 id（编辑事件里保持不变）
    reply_to: str | None = None  # 被引用消息 id
    self_id: str = ""  # 机器人自身 id，判定 @ 与自发消息需要
    edited_ts: float | None = None  # kind=edit 时的编辑时间

    # 来源与聚合
    provenance: Actor | None = None  # 转发来源；转发内容应视为不可信数据
    batch_key: str = ""  # 媒体组/相册等"一次输入多条"的聚合键
    action: str = ""  # kind=action 时的动作名（如 callback）

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            object.__setattr__(self, "kind", UNKNOWN)

    @property
    def is_group(self) -> bool:
        return self.scope.is_group

    @property
    def text(self) -> str:
        """所有 text 片段拼成的正文，供命令解析与提示词使用。"""
        return "".join(part.value for part in self.parts if part.kind == "text")

    @property
    def media_parts(self) -> tuple[Part, ...]:
        """非文本、非寻址类的片段（图片、语音、文件、表情……），原样交给 agent。"""
        return tuple(
            part for part in self.parts if part.kind not in {"text", "at", "reply"}
        )

    @property
    def mention_ids(self) -> tuple[str, ...]:
        return tuple(part.value for part in self.parts if part.kind == "at")

    @property
    def is_forwarded(self) -> bool:
        return self.provenance is not None
