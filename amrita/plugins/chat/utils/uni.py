"""uniseg 统一消息体辅助

收敛 ``nonebot_plugin_alconna.uniseg`` 的常用操作：
- 事件 → ``Target`` 转换
- 消息 ID 获取
- 按 nonebot_plugin_amrita README 推荐格式生成 user_id

所有 uniseg 导入均延迟到函数内部，避免模块加载顺序依赖。
"""

from __future__ import annotations

# 支持主动退群（set_group_leave）的平台白名单：
# OneBot V11 / OneBot V12 / Milky
GROUP_LEAVE_ADAPTERS = frozenset(
    {"OneBot V11", "OneBot V12", "Milky"}
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event
    from nonebot_plugin_alconna.uniseg import Target

# README 推荐 ID 格式：AdapterType_ExtraType_UserPayload
# 示例：QQPlatform_Group_1114514 / QQPlatform_Private_12345
#
# AdapterType 归并规则：QQ 系平台（OneBot V11/V12、Milky、QQ 官方、
# Satori-chronocat 等）按 Target.scope 统一为 ``QQPlatform``，其余平台
# 回退到适配器名。
QQ_SCOPES = frozenset({"QQClient", "QQGuild", "QQAPI"})
QQ_PLATFORM = "QQPlatform"
ADAPTER_UNKNOWN = "Unknown"


def _platform_of(target: "Target") -> str:
    """按 Target.scope 归并平台名（QQ 系 → QQPlatform）"""
    scope = target.scope
    if scope and scope in QQ_SCOPES:
        return QQ_PLATFORM
    return target.adapter or ADAPTER_UNKNOWN


def uni_target_id(target: "Target") -> str:
    """按推荐格式 ``AdapterType_ExtraType_UserPayload`` 生成 user_id

    - 群聊/频道：``{platform}_Group_{id}`` / ``{platform}_Channel_{id}``
    - 私聊：``{platform}_Private_{id}``
    - QQ 系平台统一为 ``QQPlatform``（见模块注释）
    """
    platform = _platform_of(target)
    if target.channel:
        extra = "Channel"
    elif target.private:
        extra = "Private"
    else:
        extra = "Group"
    return f"{platform}_{extra}_{target.id}"


def event_to_target(event: "Event", bot: "Bot | None" = None) -> "Target":
    """从事件提取跨适配器统一目标（uniseg Target）"""
    from nonebot_plugin_alconna.uniseg import get_target

    return get_target(event, bot)


def get_msg_id(event: "Event", bot: "Bot | None" = None) -> str:
    """获取事件对应的消息 ID（跨适配器）"""
    from nonebot_plugin_alconna.uniseg import get_message_id

    return get_message_id(event, bot)


def parse_uni_id(uni_id: str) -> tuple[str, str, str] | None:
    """解析 ``AdapterType_ExtraType_UserPayload`` 三段

    Returns:
        (adapter, extra_type, payload)；格式不符返回 None
    """
    parts = uni_id.split("_", 2)
    if len(parts) == 3 and all(parts):
        return parts[0], parts[1], parts[2]
    return None
