"""退出群聊命令：alconna 解参数 + platform 取环境。"""

from __future__ import annotations

from typing import Protocol, cast

from arclet.alconna import Alconna, Args
from nonebot.adapters import Bot
from nonebot_plugin_alconna import Match, on_alconna

from amrita.platform.di import EnvelopeNBDep
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.admin import send_to_admin

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


class _LeaveAPI(Protocol):
    async def set_group_leave(self, *, group_id: int) -> None: ...


class _QuitGroupAPI(Protocol):
    async def quit_group(self, *, group_id: int) -> None: ...


class _MemberAPI(Protocol):
    async def get_group_member_info(
        self, *, group_id: int, user_id: int, no_cache: bool = ...
    ) -> object: ...


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


async def _leave_group(bot: Bot, group_id: int) -> bool:
    """按适配器能力调用退群 API：OneBot 是 set_group_leave，Milky 是 quit_group。"""
    for name in ("set_group_leave", "quit_group"):
        method = getattr(bot, name, None)
        if method is None:
            continue
        if name == "quit_group":
            await cast(_QuitGroupAPI, bot).quit_group(group_id=group_id)
        else:
            await cast(_LeaveAPI, bot).set_group_leave(group_id=group_id)
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
    if not await _leave_group(bot, group_id):
        await set_leave.finish("❌ 当前平台不支持主动退群。")
    await set_leave.finish(f"✅ 已退出群 {group_id}！")
