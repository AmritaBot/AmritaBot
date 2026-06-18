# Pydantic Models
from collections.abc import Mapping, Sequence
from datetime import datetime

from aiologic import Lock
from amrita_core import MemoryModel as Memory
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict as PydConf
from pydantic import Field, model_validator
from typing_extensions import final

from amrita.cache import LRUCache, WeakValueLRUCache
from amrita.dirty import DirtyAwareModel as BaseModel
from amrita.plugins.chat.utils.sql import UserMetadata

from .sql import UserDataExecutor


class BaseSchema(BaseModel):
    """
    Base Schema
    """

    dirty_exclude__: tuple = Field(
        ("id", "user_id", "model_config"), exclude=True, init=False
    )

    id: int = Field(default=..., description="ID")
    user_id: str = Field(default=..., description="统一用户ID")
    model_config = PydConf(from_attributes=True, strict=False)


class AwaredMemory(Memory, BaseModel):
    """带有脏标记的Memory"""

    @model_validator(mode="before")
    @classmethod
    def validate_messages_content(cls, data):
        if isinstance(data, dict) and "messages" in data:
            messages = data["messages"]
            if isinstance(messages, list):
                # 过滤掉content内的异常消息
                filtered_messages = []
                for msg in messages:
                    if isinstance(msg, dict):
                        if (content := msg.get("content")) is not None:
                            # 检查content是否为序列（如列表、元组等）
                            if isinstance(content, Sequence) and not isinstance(
                                content, (str, bytes, Mapping)
                            ):
                                msg["content"] = [
                                    i
                                    for i in content
                                    if not (isinstance(i, dict) and len(i) in (1, 0))
                                ]
                    filtered_messages.append(msg)
                data["messages"] = filtered_messages
        return data


class UserMetadataSchema(BaseSchema):
    last_active: datetime = Field(
        default_factory=lambda: datetime.now(), description="最后活跃时间"
    )
    total_called_count: int = Field(default=0, description="长期历史调用次数")
    total_input_token: int = Field(default=0, description="总输入token数")
    total_output_token: int = Field(default=0, description="总输出token数")
    tokens_input: int = Field(default=0, description="当日输入token数")
    tokens_output: int = Field(default=0, description="当日输出token数")
    called_count: int = Field(default=0, description="当日调用次数")


class MemorySchema(BaseSchema):
    memory_json: AwaredMemory = Field(
        default_factory=AwaredMemory, description="记忆数据的JSON格式"
    )
    extra_prompt: str = Field(default="", description="额外提示")


class MemorySessionsSchema(PydanticBaseModel):  # 无脏追踪
    id: int = Field(default=..., description="ID")
    user_id: str = Field(default=..., description="统一用户ID")
    model_config = PydConf(from_attributes=True, strict=False)
    created_at: float = Field(default=0.0, description="创建时间戳")
    data: AwaredMemory = Field(
        default_factory=AwaredMemory, description="会话数据的JSON格式"
    )


class GroupConfigSchema(BaseSchema):
    enable: bool = Field(default=True, description="是否启用")
    autoreply: bool = Field(default=False, description="是否自动回复")
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(), description="最后更新时间"
    )


@final
class CachedUserDataRepository:
    _instance = None
    _action_lock: WeakValueLRUCache[str, Lock]
    _cached_group_config: LRUCache[str, GroupConfigSchema]
    _cached_memory: LRUCache[str, MemorySchema]
    _cached_metadata: LRUCache[str, UserMetadataSchema]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._cached_group_config = LRUCache(1024)  # 其次最常访问
            cls._cached_memory = LRUCache(512)
            cls._cached_metadata = LRUCache(2048)  # 最常访问
            cls._action_lock = WeakValueLRUCache(
                capacity=1024, loose_mode=True
            )  # 动态锁池
            cls._instance = super().__new__(cls)
        return cls._instance

    def make_lock(self, session_id: str) -> Lock:
        if (lock := self._action_lock.get(session_id)) is None:
            lock = Lock()
            self._action_lock.put(session_id, lock)
        return lock

    @staticmethod
    def make_uni_id(id: int, is_group: bool) -> str:
        return f"{'group' if is_group else 'user'}_{id}"

    async def get_group_config(self, group_id: int) -> GroupConfigSchema:
        uni_id = self.make_uni_id(group_id, True)
        if config := self._cached_group_config.get(uni_id):
            return config
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id) as exc:
                conf = await exc.get_or_create_group_config()
                data = GroupConfigSchema.model_validate(conf)
            self._cached_group_config[uni_id] = data
            return data

    async def get_memory(self, any_id: int, is_group: bool) -> MemorySchema:
        uni_id = self.make_uni_id(any_id, is_group)
        if data := self._cached_memory.get(uni_id):
            return data
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id) as exc:
                conf = await exc.get_or_create_memory()
                data = MemorySchema.model_validate(conf)
            self._cached_memory[uni_id] = data
            return data

    async def get_metadata(self, any_id: int, is_group: bool) -> UserMetadataSchema:
        uni_id = self.make_uni_id(any_id, is_group)
        if (
            data := self._cached_metadata.get(uni_id)
        ) and data.last_active.date() == datetime.now().date():
            return data
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id) as exc:
                conf: UserMetadata = await exc.get_or_create_metadata()
                data = UserMetadataSchema.model_validate(conf)
            self._cached_metadata[uni_id] = data
            return data

    async def get_sesssions(
        self, any_id: int, is_group: bool
    ) -> Sequence[MemorySessionsSchema]:
        """!此方法没有缓存!"""
        uni_id = self.make_uni_id(any_id, is_group)
        # 因为缓存数据可能更新不及时，并且更新也麻烦，因为它不常访问，sessions归档这里就没有再做缓存了，只是简单校验了离线模型。
        async with UserDataExecutor(uni_id) as exc:  # 这里没有缓存的逻辑，所以不带锁。
            sessions = await exc.get_or_load_sessions()
            data = [MemorySessionsSchema.model_validate(s) for s in sessions]
        return data

    async def update_group_config(self, data: GroupConfigSchema) -> None:
        uni_id = data.user_id
        dirty_attrs = data.get_dirty_vars()
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id, with_for_update=True) as exc:
                gf = await exc.get_or_create_group_config()
                for attr in dirty_attrs:
                    setattr(gf, attr, getattr(data, attr))
        data.clean()
        self._cached_group_config[uni_id] = data

    async def update_metadata(self, data: UserMetadataSchema) -> None:
        uni_id = data.user_id
        dirty = data.get_dirty_vars()
        async with self.make_lock(uni_id):
            data.last_active = datetime.now()
            async with UserDataExecutor(uni_id, with_for_update=True) as exc:
                meta = await exc.get_or_create_metadata()
                for attr in dirty:
                    setattr(meta, attr, getattr(data, attr))
        data.clean()
        self._cached_metadata[uni_id] = data

    async def update_memory_data(self, data: MemorySchema):
        uni_id = data.user_id
        dirty = data.get_dirty_vars()
        if not len(data.memory_json.get_dirty_vars()):
            dirty.discard("memory_json")
            return
        async with self.make_lock(uni_id):
            memory = data.memory_json.model_dump()
            async with UserDataExecutor(uni_id, with_for_update=True) as executor:
                dt = await executor.get_or_create_memory()
                dt.memory_json = memory
        data.clean()
        self._cached_memory[uni_id] = data
