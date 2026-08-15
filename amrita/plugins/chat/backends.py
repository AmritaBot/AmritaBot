"""Chat 插件数据后端（AmritaCore MemoryBackend 实现）"""

from amrita_core import MemoryModel
from amrita_core.base.backend import AbilityBackend, MemoryBackend
from amrita_core.contexts import AbilityContext
from amrita_core.preset import MultiPresetManager
from amrita_core.tools.manager import MultiToolsManager
from amrita_core.tools.mcp import MultiClientManager
from nonebot_plugin_amrita.memory import CachedUserDataRepository, MemorySchema


class ChatMemoryBackend(MemoryBackend):
    """绑定本次会话已预加载/预处理的 ``MemorySchema`` 的记忆后端。

    与 ``nonebot_plugin_amrita.backends.AmritaMemoryBackend`` 同构：
    ``load_memory`` 返回预处理后的 ``memory_json``，``commit_memory``
    增量写回数据库。由 Core 工作流在 ``LOAD_STATE`` / ``COMMIT_MEMORY``
    节点自动调用，无需手动注入 / 回写 ``chat.data``。
    """

    repo = CachedUserDataRepository()

    def __init__(self, memory: MemorySchema):
        self.memory_val = memory

    async def load_memory(self, session_id: str) -> MemoryModel:
        del session_id
        return self.memory_val.memory_json

    async def commit_memory(self, session_id: str, memory: MemoryModel) -> None:
        del session_id
        if self.memory_val.memory_json is not memory:
            self.memory_val.memory_json = memory
        await self.repo.update_memory_data(self.memory_val)


class NoopAbilityBackend(AbilityBackend):
    """空能力后端占位符：本插件的全部能力 fetch 均由 ``DatabackendOptions`` 跳过。"""

    async def load_ability_all(self, session_id: str) -> AbilityContext:
        del session_id
        return AbilityContext()

    async def load_mcp_clients(self, session_id: str) -> MultiClientManager:
        del session_id
        return MultiClientManager()

    async def load_tools(self, session_id: str) -> MultiToolsManager:
        del session_id
        return MultiToolsManager()

    async def load_presets(self, session_id: str) -> MultiPresetManager:
        del session_id
        return MultiPresetManager()
