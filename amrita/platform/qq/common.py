"""QQ 系平台共用逻辑：消息段转 Part、角色归一化、去重键。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable

from ..dto import (
    GROUP,
    PRIVATE,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_SYSTEM,
    MetaScalar,
    MetaValue,
    Part,
    Scope,
)

QQ = "qq"


@runtime_checkable
class SegmentLike(Protocol):
    """适配器消息段的最小形状（onebot 与 milky 都满足）。

    用只读属性而不是普通字段：字段在 Protocol 里是不变的（invariant），
    适配器的 ``dict[str, Any]`` 无法赋给 ``Mapping[str, MetaValue]``；
    属性是协变的，才能既接受 onebot 的段也接受 milky 的段。
    """

    @property
    def type(self) -> str: ...

    @property
    def data(self) -> Mapping[str, MetaValue]: ...


# 只做同义归一（mention -> at），不按用途合并：多模态类型本身是信息，合并等于替 agent 做决定。
_ALIAS = {
    "mention": "at",  # milky 的 @
    "mention_all": "at",  # @全体，值记为 "all"
    "reply": "reply",
}

_SEGMENT_VALUE_KEYS: dict[str, tuple[str, ...]] = {
    "text": ("text",),
    "at": ("qq", "user_id"),
    "mention": ("user_id", "qq"),
    "mention_all": ("qq",),
    "reply": ("message_seq", "id"),
    "image": ("url", "file", "resource_id", "temp_url"),
    "record": ("resource_id", "temp_url", "file"),
    "video": ("url", "file", "resource_id"),
    "file": ("file_name", "name", "file", "file_id"),
}


def normalize_role(role: str | None) -> str:
    """平台角色字面量 → 统一角色，未知一律降级为 member。"""
    if not isinstance(role, str):
        return ROLE_MEMBER
    match role.lower():
        case "owner" | "creator":
            return ROLE_OWNER
        case "admin" | "administrator":
            return ROLE_ADMIN
        case "system" | "bot":
            return ROLE_SYSTEM
        case _:
            return ROLE_MEMBER


def segment_to_part(segment: SegmentLike) -> Part:
    """适配器消息段 → Part。只读 ``.type`` 与 ``.data``，不 import 具体类。"""
    seg_type = str(segment.type)
    data = segment.data
    kind = _ALIAS.get(seg_type, seg_type)
    value = ""
    for key in _SEGMENT_VALUE_KEYS.get(seg_type, ()):
        candidate = data.get(key)
        if candidate is not None:
            value = str(candidate)
            break
    if not value:
        # 未知/新增媒体类型：取第一个标量字段，避免调用方还得自己翻 meta
        for candidate in data.values():
            if isinstance(candidate, str | int | float) and str(candidate):
                value = str(candidate)
                break
    if seg_type == "mention_all":
        value = "all"
    if seg_type == "text":
        value = str(data.get("text", ""))
    # meta 完整保留原始段，未知类型也不会丢信息（agent 需要时可以读）
    return Part(kind=kind, value=value, meta={"type": seg_type, "data": dict(data)})


def segments_to_parts(segments: Iterable[SegmentLike] | None) -> tuple[Part, ...]:
    if not segments:
        return ()
    return tuple(segment_to_part(segment) for segment in segments)


def dedupe_key(platform: str, kind: str, *pieces: MetaScalar) -> str:
    body = ":".join("" if piece is None else str(piece) for piece in pieces)
    return f"{platform}:{kind}:{body}"


def scope_for(
    platform: str,
    scene: str | None,
    peer_id: str | int,
    *,
    is_group: bool | None = None,
) -> Scope:
    group = is_group if is_group is not None else scene == GROUP
    return Scope(platform=platform, kind=GROUP if group else PRIVATE, id=str(peer_id))
