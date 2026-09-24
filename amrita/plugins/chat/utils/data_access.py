"""轻量数据访问层

收敛规则模块（check_rule 等）对数据库的读写，统一经由本模块访问。

当前为薄封装（效率优先，不追求完全抽象）：
直接委托 CachedUserDataRepository / CachedGroupDataRepository 单例，
后续如需替换存储实现（如迁移到其他 ORM），只需改本模块。
"""

from __future__ import annotations

from nonebot_plugin_amrita.memory import (
    CachedUserDataRepository,
    MemorySchema,
)

from .app import CachedGroupDataRepository, GroupConfigSchema
from .context_store import collapse_media_to_placeholders

__all__ = [
    "get_group_config",
    "get_memory",
    "update_group_config",
    "update_memory",
]


async def get_group_config(group_id: int) -> GroupConfigSchema:
    """获取群聊配置（带缓存与锁）"""
    return await CachedGroupDataRepository().get_group_config(group_id)


async def update_group_config(data: GroupConfigSchema) -> None:
    """更新群聊配置（带缓存与锁）"""
    await CachedGroupDataRepository().update_group_config(data)


async def get_memory(uni_id: str) -> MemorySchema:
    """获取用户/群聊记忆"""
    return await CachedUserDataRepository().get_memory(uni_id)


async def update_memory(data: MemorySchema) -> None:
    """更新用户/群聊记忆（写库前先把 base64 折叠回占位符）

    所有绕过 ``ChatMemoryBackend.commit_memory`` 的写库路径都必须走这里。
    一次中断的运行可能把展开出来的 base64 留在共享缓存中，直接写库就会把它
    持久化进 ``memory_json``。
    """
    await collapse_media_to_placeholders(data.memory_json.messages)
    await CachedUserDataRepository().update_memory_data(data)
