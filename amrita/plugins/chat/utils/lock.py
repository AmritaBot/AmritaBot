"""会话与数据库互斥锁池：统一按 uni_id 分桶，兼容按群号/用户 ID 取锁。"""

from __future__ import annotations

from collections.abc import Hashable

import aiologic

from amrita.cache import WeakValueLRUCache
from amrita.platform.dto import GROUP, PRIVATE, Scope
from amrita.platform.identity import uni_id as scope_to_uni_id

_session_lock: WeakValueLRUCache[str, aiologic.Lock] = WeakValueLRUCache(
    capacity=2048, loose_mode=True
)
_database_lock: WeakValueLRUCache[Hashable, aiologic.Lock] = WeakValueLRUCache(
    capacity=2048, loose_mode=True
)


def get_session_lock(uni_id: str) -> aiologic.Lock:
    """按统一会话主键 ``uni_id`` 取得该会话的互斥锁。"""
    if (lock := _session_lock.get(uni_id)) is None:
        lock = aiologic.Lock()
        _session_lock.put(uni_id, lock)
    return lock


def get_group_lock(id: int | str) -> aiologic.Lock:
    """QQ 群聊互斥锁过渡入口，映射至同一 ``uni_id`` 锁池。"""
    return get_session_lock(
        scope_to_uni_id(Scope(platform="qq", kind=GROUP, id=str(id)))
    )


def get_private_lock(id: int | str) -> aiologic.Lock:
    """QQ 私聊互斥锁过渡入口，映射至同一 ``uni_id`` 锁池。"""
    return get_session_lock(
        scope_to_uni_id(Scope(platform="qq", kind=PRIVATE, id=str(id)))
    )


def database_lock(*args: Hashable) -> aiologic.Lock:
    """数据库操作细粒度锁池。"""
    if (lock := _database_lock.get(args)) is None:
        lock = aiologic.Lock()
        _database_lock.put(args, lock)
    return lock
