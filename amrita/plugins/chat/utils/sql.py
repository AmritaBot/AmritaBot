from __future__ import annotations

import re
import time
from asyncio import Protocol
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from aiologic import Lock
from amrita_core.types import (
    _T,
    CT_MAP,
    T_INT,
    T_TOOL,
    BaseModel,
    Content,
    Function,
    ImageContent,
    ImageUrl,
    MemoryModel,
    Message,
    SendMessageWrap,
    T,
    TextContent,
    ToolCall,
    ToolResult,
    UniResponse,
    UniResponseUsage,
)
from amrita_core.types import (
    CONTENT_LIST_TYPE as SEND_MESSAGES,
)
from amrita_core.types import (
    CONTENT_LIST_TYPE_ITEM as SEND_MESSAGES_ITEM,
)
from nonebot.adapters.onebot.v11 import Event
from nonebot_plugin_orm import AsyncSession, Model, get_session
from pydantic import Field
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSessionTransaction
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import Self

from ..config import config_manager
from .lock import database_lock

if TYPE_CHECKING:
    from amrita.plugins.chat.utils.app import AwaredMemory


def get_uni_user_id(event: Event) -> str:
    if uid := getattr(event, "group_id", None):
        return f"group_{uid!s}"
    else:
        return f"user_{event.get_user_id()!s}"


def get_any_id(event: Event) -> tuple[int, bool]:
    if uid := getattr(event, "group_id", None):
        return uid, True
    else:
        return int(event.get_user_id()), False


VALIDATE_PATTERN = re.compile(r"^(user|group)_[0-9]+$")


def validate_uni_user_id(user_id: str) -> bool:
    return bool(VALIDATE_PATTERN.match(user_id))


class InsightsModel(BaseModel):
    date: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d"), description="日期"
    )
    token_input: int = Field(..., description="输入token使用量")
    token_output: int = Field(..., description="输出token使用量")
    usage_count: int = Field(..., description="聊天请求次数")

    @classmethod
    async def get_all(cls) -> list[Self]:
        async with database_lock():
            async with get_session() as session:
                await cls._delete_expired(
                    days=config_manager.config.usage_limit.global_insights_expire_days,
                    session=session,
                )
                stmt = select(GlobalInsights)
                insights = (await session.execute(stmt)).scalars().all()
                session.add_all(insights)
                return [cls.model_validate(x, from_attributes=True) for x in insights]

    @classmethod
    async def get(cls) -> Self:
        date_now = datetime.now().strftime("%Y-%m-%d")
        async with database_lock(date_now):
            async with get_session() as session:
                await cls._delete_expired(
                    days=config_manager.config.usage_limit.global_insights_expire_days,
                    session=session,
                )
                if (
                    insights := (
                        await session.execute(
                            select(GlobalInsights).where(
                                GlobalInsights.date == date_now
                            )
                        )
                    ).scalar_one_or_none()
                ) is None:
                    stmt = insert(GlobalInsights).values(date=date_now)
                    await session.execute(stmt)
                    insights = (
                        await session.execute(
                            select(GlobalInsights).where(
                                GlobalInsights.date == date_now
                            )
                        )
                    ).scalar_one()
                session.add(insights)
                instance = cls.model_validate(insights, from_attributes=True)
            return instance

    async def save(self):
        """保存数据"""
        async with database_lock(self.date):
            async with get_session() as session:
                await self._delete_expired(
                    days=config_manager.config.usage_limit.global_insights_expire_days,
                    session=session,
                )
                stmt = select(GlobalInsights).where(GlobalInsights.date == self.date)
                if ((await session.execute(stmt)).scalar_one_or_none()) is None:
                    stmt = insert(GlobalInsights).values(
                        **{
                            k: v
                            for k, v in self.model_dump().items()
                            if hasattr(GlobalInsights, k)
                        }
                    )
                    await session.execute(stmt)
                    await session.commit()
                else:
                    stmt = (
                        update(GlobalInsights)
                        .where(GlobalInsights.date == self.date)
                        .values(
                            **{
                                k: v
                                for k, v in self.model_dump().items()
                                if hasattr(GlobalInsights, k)
                            }
                        )
                    )
                    await session.execute(stmt)
                    await session.commit()

    @staticmethod
    async def _delete_expired(*, days: int, session: AsyncSession) -> None:
        """
        删除过期的记录

        Args:
            days: 保留天数，超过此天数的记录将被删除
        """
        # 计算截止日期
        cutoff_date = datetime.now() - timedelta(days=days)

        # 删除过期记录
        stmt = delete(GlobalInsights).where(
            GlobalInsights.date < cutoff_date.strftime("%Y-%m-%d")
        )
        await session.execute(stmt)
        await session.commit()


class HasUserIDModel(Protocol):
    user_id: Mapped[str]

    def __init__(self, **kw: Any): ...


SqlModel_T = TypeVar("SqlModel_T", bound=HasUserIDModel, contravariant=True)


class GlobalInsights(Model):
    __tablename__ = "amritabot_global_insights"
    date: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: datetime.now().strftime("%Y-%m-%d"),
    )
    token_input: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    token_output: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


class UserMetadata(Model, HasUserIDModel):
    __tablename__ = "amritabot_user_metadata"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_active: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    total_called_count: Mapped[int] = mapped_column(  # 长期的历史调用次数
        BigInteger, default=0, nullable=False
    )
    total_input_token: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    total_output_token: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    tokens_input: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )  # 当日调用
    tokens_output: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    called_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (
        Index("idx_amrita_user_id_last_active", "user_id", "last_active"),
        UniqueConstraint("user_id", name="uq_amrita_user_metadata_user_id"),
    )


class Memory(Model, HasUserIDModel):
    __tablename__ = "amritabot_memory_data"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{UserMetadata.__tablename__}.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=MemoryModel().model_dump(),
        nullable=False,
        server_default=text("'{}'"),
    )
    extra_prompt: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("user_id", name="uq_amrita_memory_user_id"),)


class MemorySessions(Model):
    __tablename__ = "amritabot_memory_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{UserMetadata.__tablename__}.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)
    data: Mapped[dict[str, Any]] = (
        mapped_column(  # Amrita的Session其实跟像一种“归档”，所以在设计时没有考虑需要修改的场景。
            JSON, nullable=False, server_default=text("'{}'")
        )
    )
    __table_args__ = (
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_created_at_time", "created_at"),
    )

    @classmethod
    async def _expire(cls, user_id: str, keep_count: int = 20):
        """
        保留特定数量的sessions，移除多余的会话记录

        Args:
            session: 数据库会话
            user_id: 用户ID
            keep_count: 要保留的会话数量，默认为20
        """
        # 查询指定user_id的所有会话，按创建时间倒序排列
        async with get_session() as session:
            stmt = (
                select(cls.id)
                .where(cls.user_id == user_id)
                .order_by(cls.created_at.desc())
                .offset(keep_count)  # 跳过要保留的数量，获取需要删除的记录
            )

            result = await session.execute(stmt)
            ids_to_delete: list[int] = [row[0] for row in result.fetchall()]

            if ids_to_delete:
                # 删除超过保留数量的会话记录
                delete_stmt = delete(cls).where(cls.id.in_(ids_to_delete))
                await session.execute(delete_stmt)

                # 提交更改
                await session.commit()

    @classmethod
    async def get(
        cls, session: AsyncSession, uni_user_id: str, no_lock: bool = False
    ) -> Sequence[Self]:
        async with database_lock(uni_user_id) if not no_lock else nullcontext():
            await cls._expire(uni_user_id, keep_count=20)
            stmt = select(cls).where(cls.user_id == uni_user_id)
            data = (await session.execute(stmt)).scalars().all()
            session.add_all(data)
            return data


class GroupConfig(Model, HasUserIDModel):
    __tablename__ = "amrita_group_config"
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{UserMetadata.__tablename__}.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    enable: Mapped[bool] = mapped_column(Boolean, default=True)
    autoreply: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_amrita_group_config_user_id"),
        Index("idx_amrita_group_config_user_id", "user_id"),
    )


class UserDataExecutor:
    session: AsyncSession
    user_id: str
    _lock: Lock
    _transaction: AsyncSessionTransaction  # (lateinit) When __aenter__ is called, this will be set
    _arg_session: AsyncSession | None = None
    _group_config_temp: GroupConfig | None = (
        None  # (lazy) This will be set when group config is accessed, and can be used to batch updates
    )
    _user_metadata_temp: UserMetadata | None = (
        None  # (lazy) This will be set when user metadata is accessed, and can be used to batch updates
    )
    _user_memory_temp: Memory | None = (
        None  # (lazy) This will be set when user memory is accessed, and can be used to batch updates
    )
    _user_sessions_temp: Sequence[MemorySessions] | None = (
        None  # (lazy) This will be set when user sessions are accessed, and can be used to batch updates
    )
    _entered: bool = False  # Mark whether the context manager has been entered, to prevent multiple __aenter__ calls
    __for_update: bool = False

    def __init__(
        self,
        user_id: str,
        session: AsyncSession | None = None,
        /,
        with_for_update: bool = False,
    ):
        if not validate_uni_user_id(user_id):
            raise ValueError(f"Invalid uni_user_id format: {user_id}")
        self.user_id = user_id
        self._arg_session = session
        self.session = session or get_session()
        self._lock = database_lock(user_id)
        self.__for_update = with_for_update

    async def __aenter__(self) -> Self:
        self._entered = True
        await self._lock.__aenter__()
        self._transaction = self.session.begin()
        if self._arg_session is None:
            await self.session.__aenter__()
        await self._transaction.__aenter__()
        self._user_metadata_temp = await (
            self.get_or_create_metadata()
        )  # Preload user metadata to prevent deadlocks later
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is not None:
                await self._transaction.rollback()
            else:
                await self._transaction.commit()
            await self._transaction.__aexit__(exc_type, exc_value, traceback)
            if self._arg_session is None:
                await self.session.__aexit__(exc_type, exc_value, traceback)
        finally:
            self._entered = False
            await self._lock.__aexit__(exc_type, exc_value, traceback)

    async def _get_or_create_any(self, model: type[SqlModel_T], **kwargs) -> SqlModel_T:
        stmt = select(model).where(model.user_id == self.user_id)
        stmt = stmt if not self.__for_update else stmt.with_for_update()
        result = await self.session.execute(stmt)
        obj = result.scalar_one_or_none()
        if obj is None:
            obj = model(user_id=self.user_id, **kwargs)
            self.session.add(obj)
            await (
                self.session.flush()
            )  # Ensure the new object is persisted before returning
        else:
            self.session.add(obj)
        return obj

    async def get_or_create_metadata(self) -> UserMetadata:
        if self._user_metadata_temp is not None:
            return self._user_metadata_temp
        data: UserMetadata = await self._get_or_create_any(UserMetadata)
        if data.last_active.date() != datetime.now().date():
            data.last_active = datetime.now()
            data.tokens_input = 0
            data.tokens_output = 0
            data.called_count = 0
        self._user_metadata_temp = data
        return data

    async def get_or_create_group_config(self) -> GroupConfig:
        if not self.user_id.startswith("group_"):
            raise ValueError("Group config can only be accessed for group users")
        if self._group_config_temp is not None:
            return self._group_config_temp
        data: GroupConfig = await self._get_or_create_any(GroupConfig)
        self._group_config_temp = data
        return data

    async def get_or_create_memory(self) -> Memory:
        if self._user_memory_temp is not None:
            return self._user_memory_temp
        data: Memory = await self._get_or_create_any(Memory, memory_json={})
        self._user_memory_temp = data
        return data

    async def get_or_load_sessions(self) -> Sequence[MemorySessions]:
        if self._user_sessions_temp is not None:
            return self._user_sessions_temp
        data: Sequence[MemorySessions] = await MemorySessions.get(
            self.session, self.user_id, no_lock=True
        )
        self.session.add_all(data)
        self._user_sessions_temp = data
        return data

    async def remove_session(self, *id: int):
        stmt = delete(MemorySessions).where(MemorySessions.id.in_(id))
        self._user_sessions_temp = [
            session
            for session in self._user_sessions_temp or []
            if session.id not in id
        ]
        await self.session.execute(stmt)

    async def add_session(self, data: AwaredMemory):
        stmt = insert(MemorySessions).values(
            user_id=self.user_id, data=data.model_dump()
        )
        await self.session.execute(stmt)

    @staticmethod
    async def get_top10_users(
        top_type: Literal["group", "private", "all"] = "all", limit: int = 10
    ) -> Sequence[UserMetadata]:
        """
        获取使用量排名前10的用户数据

        Args:
            top_type: 排名类型 ("group", "private", "all")
            limit: 返回数量限制，默认10
        """
        async with get_session() as session:
            # 确保只查询今天的记录
            today = datetime.now().date()

            # 构建基础查询
            stmt = select(UserMetadata).where(
                UserMetadata.last_active >= today,
                UserMetadata.last_active < today + timedelta(days=1),
            )

            # 根据类型过滤
            if top_type == "group":
                stmt = stmt.where(UserMetadata.user_id.like("group_%"))
            elif top_type == "private":
                stmt = stmt.where(UserMetadata.user_id.like("user_%"))
            stmt = stmt.order_by(
                UserMetadata.called_count.desc(),
                (UserMetadata.tokens_input + UserMetadata.tokens_output).desc(),
            ).limit(limit)

            result = await session.execute(stmt)
            users = result.scalars().all()
            return users


__all__ = [
    "CT_MAP",
    "SEND_MESSAGES",
    "SEND_MESSAGES_ITEM",
    "T_INT",
    "T_TOOL",
    "_T",
    "BaseModel",
    "Content",
    "Function",
    "ImageContent",
    "ImageUrl",
    "MemoryModel",
    "Message",
    "SendMessageWrap",
    "T",
    "TextContent",
    "ToolCall",
    "ToolResult",
    "UniResponse",
    "UniResponseUsage",
]
