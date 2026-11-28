"""退出群聊与 QQ 群管理辅助函数：按注册端口分派退群 / 群列表能力，不做属性反射。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, cast

from arclet.alconna import Alconna, Args
from nonebot.adapters import Bot
from nonebot_plugin_alconna import Match, on_alconna

from amrita.platform import registry
from amrita.platform.di import EnvelopeNBDep
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.admin import send_to_admin

_GROUP_OPS_ADAPTERS = frozenset({"onebot11", "milky"})

set_leave = on_alconna(
    Alconna("set_leave", Args["target?", str]),
    use_cmd_start=True,
    permission=is_lp_admin,
    default_state=MatcherData(
        name="退出指定群聊",
        description="用于退出群聊",
        usage="/set_leave [<group-id>|--this]",
        show_if="lp.admin",
    ).model_dump(),
)


class _OneBotGroupOpsAPI(Protocol):
    async def set_group_leave(self, *, group_id: int) -> None: ...

    async def get_group_list(self) -> Iterable[object]: ...

    async def get_group_member_list(self, *, group_id: int) -> Iterable[object]: ...


class _MilkyGroupOpsAPI(Protocol):
    async def quit_group(self, *, group_id: int) -> None: ...

    async def get_group_list(self) -> Iterable[object]: ...

    async def get_group_member_list(self, *, group_id: int) -> Iterable[object]: ...


class _MemberAPI(Protocol):
    async def get_group_member_info(
        self, *, group_id: int, user_id: int, no_cache: bool = ...
    ) -> object: ...


def resolve_adapter_name(bot: Bot, adapter_hint: str | None = None) -> str | None:
    """获取 Bot 对应的平台适配器名（onebot11 / milky / telegram）。"""
    if adapter_hint:
        return adapter_hint
    port = registry.resolve_bot(bot)
    return port.adapter if port is not None else None


def supports_group_list_ops(bot: Bot, adapter_hint: str | None = None) -> bool:
    """判断当前适配器是否支持群列表与群成员遍历。"""
    return resolve_adapter_name(bot, adapter_hint) in _GROUP_OPS_ADAPTERS


async def list_groups(
    bot: Bot, adapter_hint: str | None = None
) -> Iterable[object] | None:
    """拉取当前 Bot 加入的群列表；不支持该能力的平台返回 None。"""
    if not supports_group_list_ops(bot, adapter_hint):
        return None
    return await cast(_OneBotGroupOpsAPI, bot).get_group_list()


async def list_group_members(
    bot: Bot, group_id: int, adapter_hint: str | None = None
) -> Iterable[object]:
    """拉取指定群的成员列表。"""
    if resolve_adapter_name(bot, adapter_hint) == "milky":
        return await cast(_MilkyGroupOpsAPI, bot).get_group_member_list(
            group_id=group_id
        )
    return await cast(_OneBotGroupOpsAPI, bot).get_group_member_list(group_id=group_id)


async def is_group_owner(bot: Bot, group_id: int) -> bool:
    """检测 Bot 是否为指定群的群主；平台不提供成员信息时按非群主处理。"""
    api = cast(_MemberAPI, bot)
    try:
        member = await api.get_group_member_info(
            group_id=group_id, user_id=int(bot.self_id), no_cache=True
        )
    except Exception:
        return False
    if isinstance(member, dict):
        return member.get("role") == "owner"
    return getattr(member, "role", None) == "owner"


async def leave_group(
    bot: Bot, group_id: int, *, adapter_hint: str | None = None
) -> bool:
    """按适配器分派退群 API：Milky 调 quit_group，OneBot 调 set_group_leave。"""
    adapter = resolve_adapter_name(bot, adapter_hint)
    if adapter == "milky":
        await cast(_MilkyGroupOpsAPI, bot).quit_group(group_id=group_id)
        return True
    if adapter == "onebot11":
        await cast(_OneBotGroupOpsAPI, bot).set_group_leave(group_id=group_id)
        return True
    return False


@set_leave.handle()
async def leave(bot: Bot, env: EnvelopeNBDep, target: Match[str]):
    raw = str(target.result).strip() if target.available else ""

    if env.is_group:
        if not raw:
            await set_leave.finish("❌ 请输入 --this 离开当前群，或指定群号！")
        if raw == "--this":
            if env.scope.kind != "group" or not env.scope.id.isdigit():
                await set_leave.finish("❌ 当前会话不是群聊，请指定群号！")
            group_id = int(env.scope.id)
        else:
            if not raw.isdigit():
                await set_leave.finish("❌ 请输入一个数字（群号）！")
            group_id = int(raw)
    else:
        if not raw or raw == "--this":
            await set_leave.finish("❌ --this 只允许在群内使用，请指定群号！")
        if not raw.isdigit():
            await set_leave.finish("❌ 请输入一个数字（群号）！")
        group_id = int(raw)

    if await is_group_owner(bot, group_id):
        await set_leave.finish(f"❌ Bot 是群 {group_id} 的群主，无法主动退出该群！")
    await send_to_admin(f"⚠️ 尝试离开群：{group_id}")
    if not await leave_group(bot, group_id, adapter_hint=env.adapter or None):
        await set_leave.finish("❌ 当前平台不支持主动退群。")
    await set_leave.finish(f"✅ 已退出群 {group_id}！")
