from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from aiologic import Lock
from nonebot_plugin_orm import Model, get_session
from pydantic import BaseModel as B_Model
from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from amrita.cache import LRUCache, WeakValueLRUCache
from amrita.plugins.perm import nodelib
from amrita.plugins.perm.config import DataManager

PERM_TYPE = Literal["group", "user"]


class DefaultPermissionGroupsEnum(str, Enum):
    """
    默认权限组枚举类

    用于定义默认的权限组名称。
    """

    default = "default"
    default_group = "default_group"


class OnDeleteEnum(str, Enum):
    CASCADE = "CASCADE"
    RESTRICT = "RESTRICT"
    NO_ACTION = "NO ACTION"
    SET_NULL = "SET NULL"
    SET_DEFAULT = "SET DEFAULT"


class PermTypeEnum(str, Enum):
    type: PERM_TYPE
    group = "group"
    user = "user"


class PermissionGroup(Model):
    """
    权限组数据库模型

    用于在数据库中存储权限组信息。
    """

    __tablename__ = "lp_permission_group"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint("group_name", name="uq_lp_permission_group_group_name"),
        Index("idx_lp_permission_group_group_name", "group_name"),
    )


class Member2PermissionGroup(Model):
    """
    成员权限组数据库模型

    用于在数据库中存储成员（用户或群组）所属的权限组信息。
    """

    __tablename__ = "lp_member_to_permission_group"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            "lp_member_permission.member_id", ondelete=OnDeleteEnum.CASCADE.value
        ),
        nullable=False,
    )
    member_type: Mapped[PERM_TYPE] = mapped_column(String(255), nullable=False)
    group_name: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            "lp_permission_group.group_name", ondelete=OnDeleteEnum.CASCADE.value
        ),
        nullable=False,
    )
    __table_args__ = (
        UniqueConstraint(
            "member_id",
            "group_name",
            "member_type",
            name="uq_lp_member_to_permission_group_and_member",
        ),
        Index("idx_lp_member_to_permission_group_member_id", "member_id"),
        Index("idx_lp_member_to_permission_group_group_name", "group_name"),
        Index("idx_lp_member_to_permission_group_member_type", "member_type"),
    )


class MemberPermission(Model):
    """
    成员权限数据库模型

    用于在数据库中存储成员（用户或群组）的权限信息。
    """

    __tablename__ = "lp_member_permission"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[PERM_TYPE] = mapped_column(String(255), nullable=False)
    permissions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "member_id", "type", name="uq_lp_member_permission_member_id_type"
        ),
        Index("idx_lp_member_permission_member_id_type", "member_id", "type"),
    )


class BaseModel(B_Model, ABC):
    """
    权限基础模型类

    所有权限相关模型的基类，提供权限数据的基本结构和转换方法。
    """

    permissions: dict[str, Any] | None = {}

    def to_node(self):
        """
        将权限数据转换为Permissions节点对象

        Returns:
            nodelib.Permissions: 权限节点对象
        """
        return nodelib.Permissions(self.permissions)


class PermissionGroupPydantic(BaseModel):
    """
    权限组Pydantic模型

    用于表示权限组的基本信息。
    """

    group_name: str


class MemberPermissionPydantic(BaseModel):
    """
    成员权限Pydantic模型

    用于表示成员（用户或群组）的权限信息。
    """

    member_id: str
    type: PERM_TYPE


class Member2PermissionGroupPydantic(BaseModel):
    """
    成员和权限组关联Pydantic模型

    用于表示成员和权限组之间的关联关系。
    """

    member_id: str
    type: PERM_TYPE
    group_name: str


@dataclass
class MemberPermissionGroupsMeta:
    """
    成员权限组元数据类

    用于存储成员和权限组之间的关联关系。
    """

    member_id: str
    type: PERM_TYPE
    groups: list[str]


class PermissionStorage:
    """
    权限存储管理类

    该类负责管理权限组和成员权限的缓存和数据库操作，使用单例模式确保全局唯一实例。
    提供缓存机制以提高权限检查的性能，并保证数据一致性。
    """

    _instance = None
    _lock_pool: WeakValueLRUCache[str, Lock]
    _cached_permission_group_data: dict[
        str, PermissionGroupPydantic
    ]  # 缓存的权限组数据
    _cached_member_permission_data: LRUCache[
        tuple[str, PERM_TYPE], MemberPermissionPydantic
    ]  # 缓存的成员权限数据
    _cached_member_to_permission_group_data: LRUCache[
        tuple[str, PERM_TYPE], set[str]
    ]  # 权限拥有者实体ID -> 权限组名称
    _default_permission: LRUCache[tuple[str, PERM_TYPE], set[str]]

    def __new__(cls, *args, **kwargs):
        """
        创建PermissionStorage单例实例

        Returns:
            PermissionStorage: 类的单例实例
        """
        if cls._instance is None:
            config = DataManager().config
            cls._instance = super().__new__(cls)
            cls._cached_permission_group_data = {}
            cls._cached_member_permission_data = LRUCache(config.cache_size)
            cls._cached_member_to_permission_group_data = LRUCache(config.cache_size)
            cls._lock_pool = WeakValueLRUCache[str, Lock](
                capacity=2048, loose_mode=True
            )  # type: ignore[call-arg]
        return cls._instance

    def _make_lock(self, name: str) -> Lock:
        if (lock := self._lock_pool.get(name)) is None:
            lock = Lock()
            self._lock_pool.put(name, lock)
        return lock

    def _lock_maker(
        self, data: PermissionGroupPydantic | MemberPermissionPydantic
    ) -> Lock:
        """
        根据数据类型生成对应的锁

        Args:
            data (PermissionGroupPydantic | MemberPermissionPydantic): 权限数据对象

        Returns:
            Lock: 对应的锁对象

        Raises:
            ValueError: 当传入不支持的数据类型时
        """
        if isinstance(data, PermissionGroupPydantic):
            return self._make_lock(data.group_name)
        elif isinstance(data, MemberPermissionPydantic):
            return self._make_lock(str((data.member_id, data.type)))
        else:
            raise ValueError("Unsupported data type")

    async def expire_member_permission_cache(
        self,
        member_id: str,
        type: PERM_TYPE,
    ):
        """
        使指定成员权限缓存失效

        Args:
            member_id (str): 成员ID
            type (PERM_TYPE): 成员类型（"user" 或 "group"）
        """
        async with self._make_lock(str((member_id, type))):
            self._cached_member_permission_data.pop((member_id, type), None)
            self._cached_member_to_permission_group_data.pop((member_id, type), None)

    async def expire_permission_group_cache(
        self,
        group_name: str,
    ):
        """
        使指定权限组缓存失效

        Args:
            group_name (str): 权限组名称
        """
        async with self._make_lock(group_name):
            self._cached_permission_group_data.pop(group_name, None)

    async def expire_member_permission_cache_all(
        self,
    ):
        """
        使所有成员权限缓存失效
        """
        self._cached_member_permission_data.clear()
        self._cached_member_to_permission_group_data.clear()

    async def expire_permission_group_cache_all(
        self,
    ):
        """
        使所有权限组缓存失效
        """
        self._cached_permission_group_data.clear()

    async def expire_cache_all(self):
        """
        使所有缓存失效
        """
        await self.expire_member_permission_cache_all()
        await self.expire_permission_group_cache_all()

    async def permission_group_exists(self, group_name: str) -> bool:
        """
        判断权限组是否存在
        """
        if group_name in self._cached_permission_group_data:
            return True
        stmt = select(PermissionGroup).where(PermissionGroup.group_name == group_name)
        async with get_session() as session:
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def get_member_permission(
        self, member_id: str, type: PERM_TYPE, no_cache: bool = False
    ) -> MemberPermissionPydantic:
        """
        获取成员权限信息

        Args:
            member_id (str): 成员ID
            type (PERM_TYPE): 成员类型（"user" 或 "group"）
            no_cache (bool, optional): 是否跳过缓存直接从数据库获取. 默认为False

        Returns:
            MemberPermissionPydantic: 成员权限信息
        """
        async with self._make_lock(str((member_id, type))):
            if (
                not no_cache
                and (data := self._cached_member_permission_data.get((member_id, type)))
                is not None
            ):
                return data
            async with get_session() as session:
                stmt = select(MemberPermission).where(
                    MemberPermission.member_id == member_id,
                    MemberPermission.type == type,
                )
                if (
                    result := (await session.execute(stmt)).scalar_one_or_none()
                ) is None:
                    result = MemberPermission(
                        member_id=member_id,
                        type=type,
                        permissions={},
                    )
                    session.add(result)
                    await session.commit()
                    await session.refresh(result)
                data = MemberPermissionPydantic.model_validate(
                    result, from_attributes=True
                )
                self._cached_member_permission_data[(member_id, type)] = data
                return data

    async def create_permission_group(self, group_name: str) -> None:
        """
        创建权限组(不设置任何权限)

        Args:
            group_name (str): 权限组名称


        Raises:
            ValueError: 权限组存在时抛出
        """
        async with self._make_lock(group_name):
            if (
                group_name in self._cached_permission_group_data
                or await self.permission_group_exists(group_name)
            ):
                raise ValueError(f"权限组`{group_name}`已存在")
            async with get_session() as session:
                session.add(PermissionGroup(group_name=group_name, permissions={}))
                await session.commit()

    async def delete_permission_group(self, group_name: str) -> None:
        """删除权限组

        Args:
            group_name (str): 权限组名

        Raises:
            ValueError: 不存在或不合法则抛出
        """
        async with self._make_lock(group_name):
            if any(name.value == group_name for name in DefaultPermissionGroupsEnum):
                raise ValueError(f"默认权限组`{group_name}`不能删除")
            if not (
                group_name in self._cached_permission_group_data
                or await self.permission_group_exists(group_name)
            ):
                raise ValueError(f"权限组`{group_name}`不存在")
            if group_name in self._cached_permission_group_data:
                del self._cached_permission_group_data[group_name]
            async with get_session() as session:
                stmt = delete(PermissionGroup).where(
                    PermissionGroup.group_name == group_name
                )
                await session.execute(stmt)
                await session.commit()

    async def get_member_related_permission_groups(
        self,
        member_id: str,
        member_type: PERM_TYPE,
        no_cache: bool = False,
    ) -> MemberPermissionGroupsMeta:
        if (not no_cache) and (
            member_id,
            member_type,
        ) in self._cached_member_to_permission_group_data:
            return MemberPermissionGroupsMeta(
                member_id,
                member_type,
                list(
                    self._cached_member_to_permission_group_data[
                        (member_id, member_type)
                    ]
                ),
            )
        async with get_session() as session:
            stmt = select(Member2PermissionGroup).where(
                Member2PermissionGroup.member_id == member_id,
                Member2PermissionGroup.member_type == member_type,
            )
            result = await session.execute(stmt)
            data = result.scalars()
            groups = [i.group_name for i in data]
            self._cached_member_to_permission_group_data[(member_id, member_type)] = (
                set(groups)
            )
            return MemberPermissionGroupsMeta(member_id, member_type, groups)

    async def is_member_in_permission_group(
        self,
        member_id: str,
        member_type: PERM_TYPE,
        group_name: str,
        no_cache: bool = False,
    ) -> bool:
        """
        检查成员是否在权限组中

        Args:
            member_id (str): 成员id
            member_type (PERM_TYPE): 成员类型
            group_name (str): 权限组名称

        Returns:
            bool: 成员是否在权限组中
        """
        if (
            (not no_cache)
            and (member_id, member_type) in self._cached_member_to_permission_group_data
            and group_name
            in self._cached_member_to_permission_group_data[(member_id, member_type)]
        ):
            return True
        async with get_session() as session:
            stmt = select(Member2PermissionGroup).where(
                Member2PermissionGroup.member_id == member_id,
                Member2PermissionGroup.member_type == member_type,
                Member2PermissionGroup.group_name == group_name,
            )
            result = await session.execute(stmt)
            return len(result.scalars().all()) != 0

    async def del_member_related_permission_group(
        self, member_id: str, member_type: PERM_TYPE, group_name: str
    ) -> None:
        async with self._make_lock(str((member_id, member_type))):
            if not await self.is_member_in_permission_group(
                member_id, member_type, group_name
            ):
                raise ValueError(f"{member_id} {member_type} {group_name} 不在权限组中")
            self._cached_member_to_permission_group_data.pop(
                (member_id, member_type), None
            )
            async with get_session() as session:
                stmt = delete(Member2PermissionGroup).where(
                    Member2PermissionGroup.group_name == group_name,
                    Member2PermissionGroup.member_id == member_id,
                    Member2PermissionGroup.member_type == member_type,
                )
                await session.execute(stmt)
                await session.commit()

    async def add_member_related_permission_group(
        self, member_id: str, member_type: PERM_TYPE, group_name: str
    ) -> None:
        async with self._make_lock(str((member_id, member_type))):
            if not await self.is_member_in_permission_group(
                member_id, member_type, group_name
            ):
                self._cached_member_to_permission_group_data.pop(
                    (member_id, member_type), None
                )
                async with get_session() as session:
                    data = Member2PermissionGroup(
                        member_id=member_id,
                        member_type=member_type,
                        group_name=group_name,
                    )
                    session.add(data)
                    await session.commit()
            else:
                raise ValueError(
                    f"`{member_id}@{member_type}` 已经存在于 `{group_name}`"
                )

    async def get_permission_group(
        self, group_name: str, no_cache: bool = False
    ) -> PermissionGroupPydantic:
        """
        获取权限组信息，如果不存在会被隐式创建。

        Args:
            group_name (str): 权限组名称
            no_cache (bool, optional): 是否跳过缓存直接从数据库获取. 默认为False

        Returns:
            PermissionGroupPydantic: 权限组信息
        """
        async with self._make_lock(group_name):
            if (
                not no_cache
                and (data := self._cached_permission_group_data.get(group_name))
                is not None
            ):
                return data
            async with get_session() as session:
                stmt = select(PermissionGroup).where(
                    PermissionGroup.group_name == group_name
                )
                result = (await session.execute(stmt)).scalar_one_or_none()
                if not result:
                    result = PermissionGroup(group_name=group_name, permissions={})
                    session.add(result)
                    await session.commit()
                    await session.refresh(result)
                data = PermissionGroupPydantic.model_validate(
                    result, from_attributes=True
                )
                self._cached_permission_group_data[group_name] = data
                return data

    async def refresh_member_permission(
        self, member_id: str, member_type: PERM_TYPE
    ) -> MemberPermissionPydantic:
        """
        刷新成员权限缓存

        Args:
            member_id (str): 成员ID
            member_type (PERM_TYPE): 成员类型

        Returns:
            MemberPermissionPydantic: 刷新后的成员权限信息

        Raises:
            ValueError: 当找不到指定成员时
        """
        async with self._make_lock(str((member_id, member_type))):
            self._cached_member_permission_data.pop((member_id, member_type), None)
            async with get_session() as session:
                stmt = select(MemberPermission).where(
                    MemberPermission.member_id == member_id,
                    MemberPermission.type == member_type,
                )
                if (
                    result := (await session.execute(stmt)).scalar_one_or_none()
                ) is None:
                    raise ValueError(
                        f"Member `{member_id}` at `{member_type}` not found"
                    )
                data = MemberPermissionPydantic.model_validate(
                    result, from_attributes=True
                )
                self._cached_member_permission_data[(member_id, member_type)] = data
                return data

    async def refresh_permission_group(
        self, group_name: str
    ) -> PermissionGroupPydantic:
        """
        刷新权限组缓存

        Args:
            group_name (str): 权限组名称

        Returns:
            PermissionGroupPydantic: 刷新后的权限组信息

        Raises:
            ValueError: 当找不到指定权限组时
        """
        async with self._make_lock(group_name):
            self._cached_permission_group_data.pop(group_name, None)
            async with get_session() as session:
                stmt = select(PermissionGroup).where(
                    PermissionGroup.group_name == group_name
                )
                permission_group = (await session.execute(stmt)).scalar_one_or_none()
                if not permission_group:
                    raise ValueError(f"Permission group `{group_name}` not found")
                data = PermissionGroupPydantic.model_validate(
                    permission_group, from_attributes=True
                )
                self._cached_permission_group_data[group_name] = data
                return data

    async def update_permission_group(self, data: PermissionGroupPydantic):
        """
        更新权限组信息

        Args:
            data (PermissionGroupPydantic): 权限组数据
        """
        async with self._lock_maker(data):
            async with get_session() as session:
                permission_group = (
                    await session.execute(
                        select(PermissionGroup)
                        .where(PermissionGroup.group_name == data.group_name)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if permission_group is None:
                    permission_group = PermissionGroup(
                        group_name=data.group_name,
                        permissions=data.permissions,
                    )
                    session.add(permission_group)
                else:
                    permission_group.permissions = data.permissions
                await session.commit()
            self._cached_permission_group_data[data.group_name] = data

    async def update_member_permission(self, data: MemberPermissionPydantic):
        """
        更新成员权限信息

        Args:
            data (MemberPermissionPydantic): 成员权限数据
        """
        async with self._lock_maker(data):
            async with get_session() as session:
                member_permission = (
                    await session.execute(
                        select(MemberPermission).where(
                            MemberPermission.member_id == data.member_id,
                            MemberPermission.type == data.type,
                        )
                    )
                ).scalar_one_or_none()
                if member_permission is None:
                    member_permission = MemberPermission(
                        member_id=data.member_id,
                        type=data.type,
                        permissions=data.permissions,
                    )
                    session.add(member_permission)
                else:
                    member_permission.permissions = data.permissions
                await session.commit()
            self._cached_member_permission_data[(data.member_id, data.type)] = data

    async def get_all_perm_groups(
        self, no_cache: bool = False
    ) -> list[PermissionGroupPydantic]:
        if no_cache:
            async with get_session() as session:
                stmt = select(PermissionGroup)
                result = (await session.execute(stmt)).scalars().all()
                return [
                    PermissionGroupPydantic.model_validate(it, from_attributes=True)
                    for it in result
                ]
        return list(self._cached_permission_group_data.values())

    async def get_all_member_permission(
        self, type: PERM_TYPE, no_cache: bool = False
    ) -> list[MemberPermissionPydantic]:
        if no_cache:
            async with get_session() as session:
                stmt = select(MemberPermission).where(MemberPermission.type == type)
                result = (await session.execute(stmt)).scalars().all()
                return [
                    MemberPermissionPydantic.model_validate(it, from_attributes=True)
                    for it in result
                ]
        return [
            v for k, v in self._cached_member_permission_data.items() if k[1] == type
        ]

    async def init_cache_from_database(self):
        """
        从数据库初始化所有权限缓存
        """
        async with get_session() as session:
            config = await DataManager().safe_get_config()
            permission_groups = await session.execute(select(PermissionGroup))
            for permission_group in permission_groups.scalars():
                name = permission_group.group_name
                async with self._make_lock(name):
                    self._cached_permission_group_data[name] = (
                        PermissionGroupPydantic.model_validate(
                            permission_group, from_attributes=True
                        )
                    )
            del permission_groups
            members = await session.execute(
                select(MemberPermission).limit(config.cache_size)
            )
            for member in members.scalars():
                mbid, mbtype = member.member_id, member.type
                async with self._make_lock(str((mbid, mbtype))):
                    self._cached_member_permission_data[(mbid, mbtype)] = (
                        MemberPermissionPydantic.model_validate(
                            member, from_attributes=True
                        )
                    )
            del members
            perm_group_mapping = await session.execute(select(Member2PermissionGroup))
            for mapp in perm_group_mapping.scalars():
                member_type, member_id, perm_group_name = (
                    mapp.member_type,
                    mapp.member_id,
                    mapp.group_name,
                )
                key: tuple[str, Literal["group", "user"]] = (
                    member_id,
                    member_type,
                )
                if (
                    key not in self._cached_member_to_permission_group_data
                    and not self._cached_member_to_permission_group_data.is_full()
                ):
                    self._cached_member_to_permission_group_data[key] = set()
                if key in self._cached_member_to_permission_group_data:
                    self._cached_member_to_permission_group_data[key].add(
                        perm_group_name
                    )
