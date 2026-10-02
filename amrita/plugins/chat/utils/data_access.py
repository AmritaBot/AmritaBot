"""轻量数据访问层

收敛规则模块（check_rule 等）对数据库的读写，统一经由本模块访问。

当前为薄封装（效率优先，不追求完全抽象）：
直接委托 CachedUserDataRepository / CachedGroupDataRepository 单例，
后续如需替换存储实现（如迁移到其他 ORM），只需改本模块。

本模块同时收敛「历史变更」的三条语义——:func:`invalidate_usage`、
:func:`clear_history`、:func:`restore_history`。凡是改动历史内容的写库路径都
必须走这三个之一，不能只改 ``messages``：``abstract`` 与 ``usage`` 都是
*关于这份历史的*状态，历史一变它们就一起失效或一起换。
"""

from __future__ import annotations

from copy import deepcopy

from amrita_core import MemoryModel
from nonebot_plugin_amrita.memory import (
    CachedUserDataRepository,
    MemorySchema,
)

from .app import CachedGroupDataRepository, GroupConfigSchema
from .context_store import fold_media_in_messages

__all__ = [
    "clear_abstract",
    "clear_history",
    "get_group_config",
    "get_memory",
    "invalidate_usage",
    "restore_history",
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
    """更新用户/群聊记忆（写库前先把图片内容折回占位符）

    所有绕过 ``ChatMemoryBackend.commit_memory`` 的写库路径都必须走这里。
    一次中断的运行可能把展开出来的图片内容留在共享缓存中，直接写库就会把它
    持久化进 ``memory_json``。
    """
    fold_media_in_messages(data.memory_json.messages)
    await CachedUserDataRepository().update_memory_data(data)


def invalidate_usage(memory: MemoryModel) -> None:
    """作废历史的用量测量值（调用方负责写库）

    ``MemoryModel.usage`` 是**上一次 provider 请求的 payload 规模**的测量值，
    只对产生它的那份历史有意义。历史被清空或被整体替换后 payload 已不存在，
    数字却还留在 ``memory_json`` 里，``/session info`` 就会继续按它显示上下文
    大小（归档 / 失忆 / 恢复之后看起来没有归零）。

    因此凡是改动历史内容的写库路径都要调它——这也是 Core 在每次裁剪历史后
    自己做的事（``ContextCompactor.compact`` 成功后清空 ``usage``）。
    """
    memory.usage = None


def clear_abstract(memory: MemoryModel) -> None:
    """清空摘要（调用方负责写库）

    ``abstract`` 会被 train 模板渲染进系统提示，它本身就是 payload 的一部分，
    所以只清摘要也会让上一次请求的测量值失效。
    """
    memory.abstract = ""
    invalidate_usage(memory)


def clear_history(memory: MemoryModel) -> None:
    """清空历史（调用方负责写库）

    三样一起清：``messages`` 是历史本身；``abstract`` 是被折叠掉那部分的
    摘要，它描述的内容正是被清掉的东西，留下它会让 ``/session forget`` 之后
    模型依旧记得旧对话；``usage`` 描述的是已不存在的 payload。
    """
    memory.messages.clear()
    clear_abstract(memory)


def restore_history(memory: MemoryModel, source: MemoryModel) -> None:
    """把 ``source`` 的历史整体换到 ``memory``（调用方负责写库）

    与 :func:`clear_history` 对称：换历史就要把 ``abstract`` 与 ``usage``
    一起换过来，否则恢复的是一段缺了摘要、也说不清有多大的上下文。

    ``source`` 通常是归档副本，三样都是深拷贝，之后两边互不影响。
    """
    memory.messages = deepcopy(source.messages)
    memory.abstract = source.abstract
    memory.usage = deepcopy(source.usage)
