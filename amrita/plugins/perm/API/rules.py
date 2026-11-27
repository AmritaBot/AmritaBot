"""LitePerm 权限判定规则：基于归一化 Envelope 做用户与群组权限校验。"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from async_lru import alru_cache
from nonebot.adapters import Event
from nonebot.log import logger
from nonebot.message import event_postprocessor
from typing_extensions import override

from amrita.platform.di import OptionalEnvelopeNBDep
from amrita.platform.dto import META, Envelope
from amrita.platform.shim import envelope_from

from ..models import (
    DefaultPermissionGroupsEnum,
    PermissionStorage,
)
from ..nodelib import Permissions

PermTarget = Envelope | Event | None

_event_to_keys: dict[str, set[tuple[str, str, str, bool]]] = {}


def _resolve_envelope(target: PermTarget) -> Envelope | None:
    """将 Envelope 或原始 NoneBot 事件解析为 Envelope；meta 与未知事件返回 None。"""
    if target is None:
        return None
    env = (
        target if isinstance(target, Envelope) else envelope_from(target, strict=False)
    )
    if env is None or env.kind == META:
        return None
    return env


def _cache_token(env: Envelope) -> str | None:
    """事件级缓存失效键：优先 dedupe_key，缺失时退回 scope/actor/ts。"""
    if env.dedupe_key:
        return env.dedupe_key
    if env.scope.id or env.actor.user_id:
        return f"{env.scope}:{env.actor.user_id}:{env.ts}"
    return None


@event_postprocessor
async def _(env: OptionalEnvelopeNBDep) -> None:
    if env is None or env.kind == META:
        return
    token = _cache_token(env)
    if token is None:
        return
    entries = _event_to_keys.pop(token, None)
    if not entries:
        return
    for kind, member_id, permission, only_group in entries:
        if kind == "group":
            _check_group_permission_with_cache.cache_invalidate(
                member_id, permission, only_group
            )
        else:
            _check_user_permission_with_cache.cache_invalidate(member_id, permission)


@alru_cache()
async def _check_user_permission_with_cache(user_id: str, perm: str) -> bool:
    """检查用户权限的缓存函数。"""
    store = PermissionStorage()
    user_data = await store.get_member_permission(user_id, "user")
    logger.debug(f"正在检查用户权限 {user_id}:{perm}")

    if perm_groups := (
        await store.get_member_related_permission_groups(user_id, "user")
    ).groups:
        logger.info(f"正在检查用户权限组，用户ID：{user_id}")
        for permg in (*perm_groups, DefaultPermissionGroupsEnum.default.value):
            logger.debug(f"正在检查用户权限组 {permg}，用户ID：{user_id}")
            if not await store.permission_group_exists(permg):
                logger.warning(f"权限组 {permg} 不存在")
                continue
            group_data = await store.get_permission_group(permg)
            if Permissions(group_data.permissions).check_permission(perm):
                return True
    return Permissions(user_data.permissions).check_permission(perm)


@alru_cache()
async def _check_group_permission_with_cache(
    group_id: str, perm: str, only_group: bool
) -> bool:
    """检查群组权限的缓存函数。"""
    store = PermissionStorage()
    group_data = await store.get_member_permission(member_id=group_id, type="group")
    logger.debug(f"正在检查群组权限 {group_id} {perm}")
    if permd := await store.get_member_related_permission_groups(group_id, "group"):
        for permg in (*permd.groups, DefaultPermissionGroupsEnum.default_group.value):
            logger.debug(f"正在检查群组 {group_id} 的权限组 {permg}")
            if not await store.permission_group_exists(permg):
                logger.warning(f"权限组 {permg} 不存在")
                continue
            data = await store.get_permission_group(permg)
            if Permissions(data.permissions).check_permission(perm):
                return True

    return Permissions(group_data.permissions).check_permission(perm)


@dataclass
class PermissionChecker:
    """权限检查器基类。

    Args:
        permission: 权限节点名称
    """

    permission: str = field(default="")

    def __hash__(self) -> int:
        return hash(self.permission)

    def checker(self) -> Callable[[OptionalEnvelopeNBDep], Awaitable[bool]]:
        """生成可被 NoneBot Permission/Rule 使用的检查器闭包。"""
        current_perm = self.permission

        async def _checker(env: OptionalEnvelopeNBDep) -> bool:
            return await self._check_permission(env, current_perm)

        return _checker

    @abstractmethod
    async def _check_permission(self, target: PermTarget, perm: str) -> bool:
        raise NotImplementedError("Awaitable '_check_permission' not implemented")


@dataclass
class UserPermissionChecker(PermissionChecker):
    """用户权限检查器。"""

    def __hash__(self) -> int:
        return hash(self.permission)

    @override
    async def _check_permission(self, target: PermTarget, perm: str) -> bool:
        env = _resolve_envelope(target)
        if env is None or not env.actor.user_id:
            return False
        user_id = env.actor.user_id
        if token := _cache_token(env):
            _event_to_keys.setdefault(token, set()).add(("user", user_id, perm, False))
        return await _check_user_permission_with_cache(user_id, perm)


@dataclass
class GroupPermissionChecker(PermissionChecker):
    """群组权限检查器。

    Args:
        only_group: 为 False 时，非群聊会话直接放行
    """

    only_group: bool = True

    def __hash__(self) -> int:
        return hash((self.permission, self.only_group))

    @override
    async def _check_permission(self, target: PermTarget, perm: str) -> bool:
        env = _resolve_envelope(target)
        if env is None:
            return False
        if not env.is_group:
            return not self.only_group
        group_id = env.scope.id
        if token := _cache_token(env):
            _event_to_keys.setdefault(token, set()).add(
                ("group", group_id, perm, self.only_group)
            )
        return await _check_group_permission_with_cache(group_id, perm, self.only_group)


async def has_any_permission(target: PermTarget, permission: str) -> bool:
    """检查目标（Envelope 或原始事件）的群组或用户任一是否持有指定权限。"""
    resolved = _resolve_envelope(target)
    if resolved is None:
        return False
    return (
        await GroupPermissionChecker(permission, True)._check_permission(
            resolved, permission
        )
    ) or (
        await UserPermissionChecker(permission)._check_permission(resolved, permission)
    )


def any_has_permission(
    permission: str,
) -> Callable[[OptionalEnvelopeNBDep], Awaitable[bool]]:
    """生成“群组或用户任一持有该权限即放行”的 NoneBot 权限检查器。"""

    async def inner(env: OptionalEnvelopeNBDep) -> bool:
        return await has_any_permission(env, permission)

    return inner
