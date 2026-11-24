"""事件取值兜底：把"取不到"变成可判定的 None，而不是直接抛异常。"""

from __future__ import annotations

from nonebot.adapters import Event


def event_user_id(event: Event) -> str | None:
    """事件发起者 ID；meta 事件（心跳/生命周期）没有发起者，返回 ``None``。

    ``Event.get_user_id()`` 依赖事件上下文，心跳这类事件调用会抛
    ``ValueError: Event has no context!``。权限检查、规则这类不区分事件类型的
    地方必须先拿到 ``None`` 再决定放行，而不是让异常冒到事件分发里。
    """
    for holder in (event, getattr(event, "sender", None)):
        value = getattr(holder, "user_id", None)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value:
            return value
    try:
        return event.get_user_id() or None
    except Exception:
        return None


__all__ = ["event_user_id"]
