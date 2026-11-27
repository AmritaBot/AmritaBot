"""LitePerm 管理员判定：支持 SUPERUSERS 与 lp.admin 权限节点。"""

from __future__ import annotations

from nonebot import get_driver

from amrita.platform.di import OptionalEnvelopeNBDep

from ..config import DataManager
from .rules import PermTarget, _resolve_envelope, has_any_permission

ENV_ADMINS = get_driver().config.superusers


async def is_lp_admin(env: OptionalEnvelopeNBDep) -> bool:
    """判断当前事件发起者是否为管理员；meta 与未识别事件静默返回 False。"""
    return await is_lp_admin_for(env)


async def is_lp_admin_for(target: PermTarget) -> bool:
    """对 Envelope 或原始事件执行管理员校验，供非 DI 场景显式调用。"""
    resolved = _resolve_envelope(target)
    if resolved is None or not resolved.actor.user_id:
        return False

    return (
        resolved.actor.user_id in ENV_ADMINS
        or await has_any_permission(resolved, "lp.admin")
    ) and DataManager().config.enable
