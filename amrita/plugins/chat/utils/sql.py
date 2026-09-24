from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from aiologic import Lock
from nonebot.adapters.onebot.v11 import Event
from nonebot_plugin_amrita.database import (
    HasUserIDModel,
    Memory,
    SqlModel_T,
    UserMetadata,
)
from nonebot_plugin_orm import AsyncSession, Model, get_session
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSessionTransaction
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import Self

from .lock import database_lock

QQ_PLATFORM = "QQPlatform"
"""QQ 系平台在会话 ID 中的适配器名"""

#  nonebot_plugin_amrita 推荐格式：AdapterType_ExtraType_UserPayload（如 QQPlatform_Private_12345）
_UNI_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+_(Private|Group|Channel)_([0-9]+)$")
#  v1.8.0 及更早的历史格式：user_{qq} / group_{群号}
_LEGACY_UNI_ID_PATTERN = re.compile(r"^(user|group)_([0-9]+)$")

_EXTRA_PRIVATE = "Private"
_EXTRA_GROUP = "Group"


def get_uni_user_id(event: Event) -> str:
    if uid := getattr(event, "group_id", None):
        return make_uni_id(uid, is_group=True)
    else:
        return make_uni_id(event.get_user_id(), is_group=False)


async def get_user_metadata_or_none(uni_user_id: str) -> UserMetadata | None:
    """只读查询指定 uni_user_id 的元数据，不存在时返回 None（不会创建记录）"""
    async with get_session() as session:
        stmt = select(UserMetadata).where(UserMetadata.user_id == uni_user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


def get_any_id(event: Event) -> tuple[int, bool]:
    if uid := getattr(event, "group_id", None):
        return uid, True
    else:
        return int(event.get_user_id()), False


def make_uni_id(id: int | str, is_group: bool) -> str:
    """生成会话 ID：``QQPlatform_Group_{群号}`` / ``QQPlatform_Private_{QQ}``"""
    extra = _EXTRA_GROUP if is_group else _EXTRA_PRIVATE
    return f"{QQ_PLATFORM}_{extra}_{id!s}"


def parse_uni_user_id(user_id: str) -> tuple[str, int] | None:
    """解析会话 ID 为 ``(ExtraType, payload)``，格式不符返回 None

    兼容 v1.8.0 及更早的 ``user_{qq}`` / ``group_{群号}``，用于读取尚未迁移的历史数据。
    """
    if match := _UNI_ID_PATTERN.match(user_id):
        return match.group(1), int(match.group(2))
    if match := _LEGACY_UNI_ID_PATTERN.match(user_id):
        kind = match.group(1)
        return (_EXTRA_GROUP if kind == "group" else _EXTRA_PRIVATE), int(
            match.group(2)
        )
    return None


def validate_uni_user_id(user_id: str) -> bool:
    return parse_uni_user_id(user_id) is not None


def is_group_uni_id(user_id: str) -> bool:
    """判断会话 ID 是否代表群聊（兼容历史 ``group_`` 前缀）"""
    parsed = parse_uni_user_id(user_id)
    return parsed is not None and parsed[0] == _EXTRA_GROUP


def validate_and_ret(uid: str) -> str:
    if validate_uni_user_id(uid):
        return uid
    raise ValueError(f"Invalid uni_user_id: {uid}")


def unwrap_uni_user_id(user_id: str) -> tuple[Literal["user", "group"], int]:
    parsed = parse_uni_user_id(user_id)
    if parsed is None:
        raise ValueError(f"Invalid uni_user_id: {user_id}")
    kind: Literal["user", "group"] = "group" if parsed[0] == _EXTRA_GROUP else "user"
    return kind, parsed[1]


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


class GroupConfigExecutor:
    session: AsyncSession
    group_id: str
    _lock: Lock
    _transaction: AsyncSessionTransaction  # (lateinit) When __aenter__ is called, this will be set
    _arg_session: AsyncSession | None = None
    _group_config_temp: GroupConfig | None = (
        None  # (lazy) This will be set when group config is accessed, and can be used to batch updates
    )
    _entered: bool = False  # Mark whether the context manager has been entered, to prevent multiple __aenter__ calls
    __for_update: bool = False

    def __init__(
        self,
        group_id: str,
        session: AsyncSession | None = None,
        /,
        with_for_update: bool = False,
    ):
        if not validate_uni_user_id(group_id):
            raise ValueError(f"Invalid uni_user_id format: {group_id}")
        self.group_id = group_id
        self._arg_session = session
        self.session = session or get_session()
        self._lock = database_lock(group_id)
        self.__for_update = with_for_update

    async def __aenter__(self) -> Self:
        self._entered = True
        await self._lock.__aenter__()
        self._transaction = self.session.begin()
        if self._arg_session is None:
            await self.session.__aenter__()
        await self._transaction.__aenter__()
        # Ensure UserMetadata row exists to satisfy FK constraint
        stmt = select(UserMetadata.id).where(UserMetadata.user_id == self.group_id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is None:
            self.session.add(UserMetadata(user_id=self.group_id))
            await self.session.flush()
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
        stmt = select(model).where(model.user_id == self.group_id)
        stmt = stmt if not self.__for_update else stmt.with_for_update()
        result = await self.session.execute(stmt)
        obj = result.scalar_one_or_none()
        if obj is None:
            obj = model(user_id=self.group_id, **kwargs)
            self.session.add(obj)
            await (
                self.session.flush()
            )  # Ensure the new object is persisted before returning
        else:
            self.session.add(obj)
        return obj

    async def get_or_create_group_config(self) -> GroupConfig:
        if not is_group_uni_id(self.group_id):
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
