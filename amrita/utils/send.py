"""公共出站与合并转发封装：业务层只读 Sender.capabilities 决定合并转发或文本降级。"""

from __future__ import annotations

from collections.abc import Iterable

from nonebot.adapters import Bot, Event, MessageSegment

from amrita.platform import registry
from amrita.platform.dto import GROUP, PRIVATE, Envelope, Part, Scope
from amrita.platform.ports import CAP_FORWARD, Sender
from amrita.platform.shim import envelope_from

from .events import event_user_id

ForwardTarget = Envelope | Scope | Event
ForwardItem = str | Part | MessageSegment


def _item_to_part(item: ForwardItem) -> Part:
    """统一将文本 / Part / NoneBot MessageSegment 转为平台无关的 Part。"""
    if isinstance(item, Part):
        return item
    if isinstance(item, str):
        return Part(kind="text", value=item)
    if isinstance(item, MessageSegment):
        if item.is_text():
            return Part(kind="text", value=str(item.data.get("text", "")))
        return Part(
            kind=item.type,
            value=str(item.data.get("text") or item.data.get("file") or item),
            meta={"type": item.type, "data": dict(item.data)},
        )
    return Part(kind="text", value=str(item))


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


def resolve_sender(
    bot: Bot, scope: Scope, *, adapter: str | None = None
) -> Sender | None:
    """按 adapter、Bot 端口归属或 platform 查找平台端口并创建 Sender。"""
    port = registry.get_adapter(adapter) if adapter else None
    if port is None:
        matched = registry.resolve_bot(bot)
        if matched is not None and matched.name == scope.platform:
            port = matched
    if port is None:
        try:
            port = registry.get(scope.platform)
        except LookupError:
            return None
    return port.sender(bot, scope)


async def send_forward_msg(
    bot: Bot,
    event: ForwardTarget,
    name: str,
    uin: str,
    msgs: Iterable[ForwardItem],
) -> None:
    """向目标会话发送多段信息：支持 CAP_FORWARD 的平台走合并转发，其余降级为文本发送。"""
    parts = [_item_to_part(item) for item in msgs]
    if not parts:
        return

    scope, adapter = _resolve_scope_and_adapter(bot, event)
    if scope is None:
        raise ValueError("event has no target scope or user id")

    sender = resolve_sender(bot, scope, adapter=adapter)
    if sender is not None and sender.supports(CAP_FORWARD):
        await sender.send_forward(parts, name=name, uin=uin)
        return

    text_blocks = [t for part in parts if (t := part.value.strip())]
    if not text_blocks:
        return
    combined = (
        f"[{name}]\n" + "\n\n".join(text_blocks) if name else "\n\n".join(text_blocks)
    )
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
