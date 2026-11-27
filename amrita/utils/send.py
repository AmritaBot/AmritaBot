"""公共出站与合并转发封装：业务层决定合并转发还是文本降级。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from importlib import import_module
from typing import Protocol, cast

from nonebot.adapters import Bot, Event

from amrita.platform import registry
from amrita.platform.dto import GROUP, PRIVATE, Envelope, Part, Scope
from amrita.platform.ports import Sender
from amrita.platform.shim import envelope_from

from .events import event_user_id

ForwardTarget = Envelope | Scope | Event
ForwardItem = str | Part | object


class _OneBotForwardAPI(Protocol):
    async def send_group_forward_msg(
        self, *, group_id: int, messages: list[dict[str, object]]
    ) -> object: ...

    async def send_private_forward_msg(
        self, *, user_id: int, messages: list[dict[str, object]]
    ) -> object: ...


class _MilkyForwardAPI(Protocol):
    async def send_group_message(self, *, group_id: int, message: object) -> object: ...

    async def send_private_message(
        self, *, user_id: int, message: object
    ) -> object: ...


class _MilkyMessageFactory(Protocol):
    def __call__(self, segments: Sequence[object]) -> object: ...


class _MilkyForwardFragments(Protocol):
    @staticmethod
    def text(content: str) -> object: ...

    @staticmethod
    def image(url: str | None = None) -> object: ...

    @staticmethod
    def node(
        user_id: int, name: str, segments: object, time: int | None = None
    ) -> object: ...

    @staticmethod
    def forward(
        messages: list[object],
        title: str | None = None,
        preview: list[str] | None = None,
        summary: str | None = None,
        prompt: str | None = None,
    ) -> object: ...


def _item_to_text(item: ForwardItem) -> str:
    """将文本 / Part / 适配器 MessageSegment 转为纯文本，用于不支持转发时的降级发送。"""
    if isinstance(item, str):
        return item
    if isinstance(item, Part):
        return item.value
    is_text = getattr(item, "is_text", None)
    if callable(is_text) and is_text():
        data = getattr(item, "data", None)
        if isinstance(data, dict):
            text = data.get("text")
            if isinstance(text, str):
                return text
    data = getattr(item, "data", None)
    if isinstance(data, dict):
        text = data.get("text")
        if isinstance(text, str):
            return text
    return str(item)


def _item_to_forward_content(item: ForwardItem) -> object:
    """转为 OneBot 合并转发节点的 content 字段：原生段直接透传，Part 取值，其余转字符串。"""
    if isinstance(item, str):
        return item
    if isinstance(item, Part):
        if item.kind == "text":
            return item.value
        raw_type = item.meta.get("type")
        raw_data = item.meta.get("data")
        if isinstance(raw_type, str) and isinstance(raw_data, dict):
            return {"type": raw_type, "data": raw_data}
        return item.value
    if hasattr(item, "type") and hasattr(item, "data"):
        return item
    return str(item)


def _load_milky_factories() -> (
    tuple[_MilkyMessageFactory, _MilkyForwardFragments] | None
):
    try:
        module = import_module("nonebot.adapters.milky.message")
    except ImportError:
        return None
    message = cast(_MilkyMessageFactory, getattr(module, "Message"))
    fragments = cast(_MilkyForwardFragments, getattr(module, "MessageSegment"))
    return message, fragments


def _build_milky_forward_payload(
    name: str, uin: str, items: Sequence[ForwardItem]
) -> object:
    """构造 Milky 合并转发消息段；装了 adapter 用原生 MessageSegment.forward，否则退化为协议 dict。"""
    uid = int(uin) if uin.isdigit() else 0
    factories = _load_milky_factories()
    if factories is not None:
        message_factory, fragments = factories
        nodes: list[object] = []
        for item in items:
            if isinstance(item, Part) and item.kind == "image" and item.value:
                seg = fragments.image(item.value)
            else:
                seg = fragments.text(_item_to_text(item))
            nodes.append(
                fragments.node(user_id=uid, name=name, segments=message_factory([seg]))
            )
        return message_factory([fragments.forward(messages=nodes, title=name or None)])

    # 未安装 nonebot-adapter-milky（例如单测 stub Bot）时按 Milky OutgoingSegment 协议结构组装
    raw_nodes: list[dict[str, object]] = []
    for item in items:
        if isinstance(item, Part) and item.kind == "image" and item.value:
            seg_dict: dict[str, object] = {
                "type": "image",
                "data": {"uri": item.value},
            }
        else:
            seg_dict = {"type": "text", "data": {"text": _item_to_text(item)}}
        raw_nodes.append({"user_id": uid, "sender_name": name, "segments": [seg_dict]})
    return [{"type": "forward", "data": {"messages": raw_nodes, "title": name or None}}]


def _resolve_scope_and_adapter(
    bot: Bot, target: ForwardTarget
) -> tuple[Scope | None, str | None]:
    """从 Envelope / Scope / 原始 Event 中提取出站目标 Scope 与 adapter 提示。"""
    if isinstance(target, Envelope):
        return target.scope, target.adapter or None
    if isinstance(target, Scope):
        return target, None
    env = envelope_from(target, bot, strict=False)
    if env is not None:
        return env.scope, env.adapter or None
    gid = getattr(target, "group_id", None)
    if isinstance(gid, int) and gid:
        return Scope(platform="qq", kind=GROUP, id=str(gid)), None
    uid = event_user_id(target)
    if uid is not None:
        return Scope(platform="qq", kind=PRIVATE, id=str(uid)), None
    return None, None


def _bot_adapter_hint(bot: Bot) -> str | None:
    """从 Bot 类模块路径推测平台适配器名，仅作无 Envelope 时的兜底。"""
    module = type(bot).__module__
    if "nonebot.adapters.onebot" in module:
        return "onebot11"
    if "nonebot.adapters.milky" in module:
        return "milky"
    if "nonebot.adapters.telegram" in module:
        return "telegram"
    return None


def resolve_sender(
    bot: Bot, scope: Scope, *, adapter: str | None = None
) -> Sender | None:
    """按 adapter 或 platform 查找平台端口并创建 Sender；无匹配端口返回 None。"""
    hint = adapter or _bot_adapter_hint(bot)
    port = registry.get_adapter(hint) if hint else None
    if port is None:
        try:
            port = registry.get(scope.platform)
        except LookupError:
            return None
    return port.sender(bot, scope)


def _has_explicit_method(bot: Bot, name: str) -> bool:
    """排除 NoneBot Bot.__getattr__ 的动态兜底，只认真实定义或实例注入的方法。"""
    return hasattr(type(bot), name) or name in bot.__dict__


def _supports_onebot_forward(bot: Bot, scope: Scope, adapter: str | None) -> bool:
    """只有 OneBot v11 且具备对应转发 API 与数字会话 ID 时才走合并转发节点。"""
    if not scope.id.isdigit():
        return False
    hint = adapter or _bot_adapter_hint(bot)
    if hint == "onebot11":
        return True
    if hint is not None:
        return False
    method_name = (
        "send_group_forward_msg" if scope.is_group else "send_private_forward_msg"
    )
    return _has_explicit_method(bot, method_name)


def _supports_milky_forward(bot: Bot, scope: Scope, adapter: str | None) -> bool:
    """Milky 同属 QQ 平台，原生通过 OutgoingSegment(type='forward') 支持合并转发。"""
    if not scope.id.isdigit():
        return False
    hint = adapter or _bot_adapter_hint(bot)
    return hint == "milky"


async def send_forward_msg(
    bot: Bot,
    event: ForwardTarget,
    name: str,
    uin: str,
    msgs: Iterable[ForwardItem],
) -> None:
    """向目标会话发送多段信息：OneBot v11 与 Milky 走合并转发，其余平台降级为文本发送。"""
    items = list(msgs)
    if not items:
        return

    scope, adapter = _resolve_scope_and_adapter(bot, event)
    if scope is None:
        raise ValueError("event has no target scope or user id")

    if _supports_onebot_forward(bot, scope, adapter):
        messages = [
            {
                "type": "node",
                "data": {
                    "name": name,
                    "uin": uin,
                    "content": _item_to_forward_content(item),
                },
            }
            for item in items
        ]
        api = cast(_OneBotForwardAPI, bot)
        if scope.is_group:
            await api.send_group_forward_msg(group_id=int(scope.id), messages=messages)
        else:
            await api.send_private_forward_msg(user_id=int(scope.id), messages=messages)
        return

    if _supports_milky_forward(bot, scope, adapter):
        payload = _build_milky_forward_payload(name, uin, items)
        api_milky = cast(_MilkyForwardAPI, bot)
        if scope.is_group:
            await api_milky.send_group_message(group_id=int(scope.id), message=payload)
        else:
            await api_milky.send_private_message(user_id=int(scope.id), message=payload)
        return

    text_blocks = [t for item in items if (t := _item_to_text(item).strip())]
    if not text_blocks:
        return
    combined = (
        f"[{name}]\n" + "\n\n".join(text_blocks) if name else "\n\n".join(text_blocks)
    )
    sender = resolve_sender(bot, scope, adapter=adapter)
    if sender is not None:
        await sender.send_text(combined)
        return
    if isinstance(event, Event):
        await bot.send(event, combined)
        return
    raise RuntimeError(f"no sender available for scope {scope}")


__all__ = [
    "ForwardItem",
    "ForwardTarget",
    "resolve_sender",
    "send_forward_msg",
]
