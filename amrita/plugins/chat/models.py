"""Chat 插件的上下文静默存储数据模型。

设计要点：

- 未被触发的群消息不再写入 LLM 记忆（避免污染上下文），而是静默落库到
  :class:`ContextRecord`，由 ``read_context`` 工具按需读取；
- 多模态二进制内容本地落库到 :class:`ContextMedia`，上下文中仅保留
  :class:`PlaceholderContent` 占位符（``media_id`` = 二进制内容的 sha256），
  读取时再还原为 base64 data URI；
- 两张表都按 :class:`~amrita.plugins.chat.config.ContextStoreConfig` 中配置的
  条数 / 时间上限淘汰。

ORM 声明风格与 ``amrita/plugins/manager/models.py``、``amrita/plugins/chat/utils/sql.py``
保持一致（``nonebot_plugin_orm.Model`` + SQLAlchemy 2.0 ``Mapped`` / ``mapped_column``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from amrita_core.types import Content, register_content
from nonebot_plugin_orm import Model
from pydantic import Field
from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = [
    "ContextMedia",
    "ContextRecord",
    "PlaceholderContent",
]

#  二进制列类型：MySQL 方言把不带 length 的 LargeBinary 渲染成 64KB BLOB，与 max_image_kb 冲突，故显式改用 LONGBLOB
_MEDIA_BINARY_TYPE = LargeBinary().with_variant(LONGBLOB(), "mysql")


class PlaceholderContent(Content[Literal["placeholder"]]):
    """多模态内容的占位符。

    上下文中只保留它（不含二进制本体），``media_id`` 为二进制内容的
    sha256 十六进制摘要，用于从 :class:`ContextMedia` 取回原始数据。
    """

    type: Literal["placeholder"] = "placeholder"
    media_id: str = Field(..., description="媒体内容 ID（二进制内容的 sha256 hex）")
    kind: Literal["image"] = Field(default="image", description="媒体类型")
    mime: str = Field(default="image/jpeg", description="媒体 MIME 类型")
    size: int = Field(default=0, description="媒体体积（字节）")
    description: str = Field(default="", description="媒体描述，可为空")


# 向 AmritaCore 注册自定义 Content 类型，必须早于任何 Message.model_validate（含记忆反序列化），故本模块最早导入
register_content(PlaceholderContent)


class ContextRecord(Model):
    """群聊静默上下文记录（替代原先把群消息写入记忆的做法）。"""

    __tablename__ = "amrita_chat_context_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #  会话 ID（QQPlatform_Group_xxx / QQPlatform_Private_xxx），见 utils/sql.py:make_uni_id
    uni_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    nickname: Mapped[str] = mapped_column(String(128), default="")
    #  消息发送者在群内的角色（群主/群管理员/普通成员）
    role: Mapped[str] = mapped_column(String(32), default="")
    #  已按 XML 格式渲染、可直接喂给 LLM 的文本（旧记录可能为 legacy 格式）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    __table_args__ = (
        Index("idx_amrita_ctx_record_uni_time", "uni_id", "created_at"),
        Index("idx_amrita_ctx_record_created", "created_at"),
    )


class ContextMedia(Model):
    """多模态二进制内容本地存储（按 sha256 去重）。"""

    __tablename__ = "amrita_chat_context_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #  首次入库时所属的会话 ID（仅用于排障与统计）
    uni_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(_MEDIA_BINARY_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("media_id", name="uq_amrita_chat_context_media_id"),
        Index("idx_amrita_ctx_media_uni", "uni_id"),
        Index("idx_amrita_ctx_media_created", "created_at"),
    )
