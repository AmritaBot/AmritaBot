"""出站与入站端口：Sender / PlatformPort，能力表如实声明平台能做什么。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from nonebot.adapters import Bot
from pydantic import BaseModel

from .dto import Actor, Envelope, Part, Scope

# 出站能力名
CAP_TEXT = "text"
CAP_IMAGE = "image"
CAP_AT = "at"
CAP_REPLY = "reply"
CAP_RECALL = "recall"
CAP_FORWARD = "forward"  # 合并转发（QQ 系 OneBot / Milky 等）
# 预留：暂未由 QQ 侧实现，给 Telegram 这类平台留位
CAP_THREAD = "thread"  # 发到话题/子区
CAP_EDIT = "edit"  # 编辑已发送消息
CAP_TYPING = "typing"  # "正在输入"指示
CAP_MARKUP = "markup"  # 按钮 / 内联键盘


class CapabilityMissing(RuntimeError):
    """调用了平台不支持的能力。

    业务层应当先查 ``sender.capabilities``；直接调用是编码错误而非运行期异常。
    """


@runtime_checkable
class Sender(Protocol):
    """出站端口：只暴露能力，不暴露具体 Bot。"""

    capabilities: frozenset[str]

    def supports(self, capability: str) -> bool: ...

    async def send_text(
        self,
        text: str,
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        """发送纯文本，返回消息 id（不可用时返回空串）。"""
        ...

    async def send_parts(
        self,
        parts: Sequence[Part],
        *,
        reply_to: str | None = None,
        thread: str | None = None,
    ) -> str:
        """发送富消息体，返回消息 id。"""
        ...

    async def send_forward(
        self,
        nodes: Sequence[Part],
        *,
        name: str = "",
        uin: str = "",
    ) -> str:
        """发送合并转发消息；需要 ``CAP_FORWARD``。"""
        ...

    async def recall(self, message_id: str) -> bool:
        """撤回消息，成功返回 True；平台不支持或过期返回 False。"""
        ...

    async def edit(self, message_id: str, parts: Sequence[Part]) -> bool:
        """编辑已发送消息；需要 ``CAP_EDIT``。"""
        ...

    async def typing(self) -> None:
        """发送"正在输入"指示；需要 ``CAP_TYPING``，失败静默。"""
        ...


@runtime_checkable
class PlatformPort(Protocol):
    """入站端口：一个 platform 下可以有多个 adapter 实现。"""

    name: str
    adapter: str

    def match(self, raw_event: BaseModel, bot: Bot | None = None) -> bool: ...

    def to_envelope(self, raw_event: BaseModel, bot: Bot | None = None) -> Envelope: ...

    def sender(self, bot: Bot, scope: Scope) -> Sender: ...

    async def resolve_role(self, bot: Bot, scope: Scope, actor: Actor) -> Actor:
        """事件没带角色时向平台查询，返回补全后的 Actor。

        查不到、平台不支持、或本来就有角色时，原样返回 ``actor``。
        实现方可以自行缓存，但不得改变"查不到就是查不到"的语义——
        绝不猜测成 admin。
        """
        ...


class BaseSender:
    """Sender 的公共部分：能力判定、缺能力报错、可选能力的默认实现。"""

    capabilities: frozenset[str] = frozenset()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def _require(self, capability: str) -> None:
        if capability not in self.capabilities:
            raise CapabilityMissing(
                f"platform does not support {capability!r}: {sorted(self.capabilities)}"
            )

    async def send_forward(
        self,
        nodes: Sequence[Part],
        *,
        name: str = "",
        uin: str = "",
    ) -> str:
        self._require(CAP_FORWARD)
        raise NotImplementedError

    async def edit(self, message_id: str, parts: Sequence[Part]) -> bool:
        if not self.supports(CAP_EDIT):
            return False
        raise NotImplementedError

    async def typing(self) -> None:
        if not self.supports(CAP_TYPING):
            return
        raise NotImplementedError
