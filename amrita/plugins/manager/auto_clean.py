"""无用群组清理命令：Alconna + 按适配器能力调用群列表/退群 API。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, cast

from arclet.alconna import Alconna, Option
from nonebot import get_driver, logger
from nonebot.adapters import Bot
from nonebot_plugin_alconna import AlconnaResult, CommandResult, on_alconna

from amrita import get_amrita_config
from amrita.platform.di import EnvelopeNBDep
from amrita.platform.dto import GROUP, Scope
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.send import resolve_sender

from .leave import _leave_group, is_group_owner

clean_groups = on_alconna(
    Alconna("clean_groups", Option("--confirm")),
    use_cmd_start=True,
    permission=is_lp_admin,
    default_state=MatcherData(
        name="无用群组清理",
        description="清理人数小于20的无效群聊",
        usage="/clean_groups [--confirm]",
        show_if="lp.admin",
    ).model_dump(),
)


class _GroupListAPI(Protocol):
    async def get_group_list(self) -> Iterable[object]: ...

    async def get_group_member_list(self, *, group_id: int) -> Iterable[object]: ...


def _extract_group_info(item: object) -> tuple[int, str] | None:
    if isinstance(item, dict):
        gid = item.get("group_id")
        name = item.get("group_name", "")
    else:
        gid = getattr(item, "group_id", None)
        name = getattr(item, "group_name", None) or getattr(item, "name", "")
    if isinstance(gid, int):
        return gid, str(name)
    if isinstance(gid, str) and gid.isdigit():
        return int(gid), str(name)
    return None


def _extract_member_id(item: object) -> int | None:
    if isinstance(item, dict):
        uid = item.get("user_id")
    else:
        uid = getattr(item, "user_id", None)
    if isinstance(uid, int):
        return uid
    if isinstance(uid, str) and uid.isdigit():
        return int(uid)
    return None


def _superuser_int_ids() -> set[int]:
    """提取 SUPERUSERS 中的数字 ID（兼容裸 ID、platform:id 与 uni_id）。"""
    ids: set[int] = set()
    for raw in get_driver().config.superusers:
        token = raw.rsplit(":", 1)[-1].rsplit("_", 1)[-1]
        if token.isdigit():
            ids.add(int(token))
    return ids


@clean_groups.handle()
async def _(
    bot: Bot,
    env: EnvelopeNBDep,
    result: CommandResult = AlconnaResult(),
):
    if not result.result.find("confirm"):
        await clean_groups.finish(
            "⚠️ 该操作会批量退出人数少于20人的群组，确认执行请再次输入：/clean_groups --confirm"
        )
    module = type(bot).__module__
    has_group_api = (
        "nonebot.adapters.onebot" in module
        or "nonebot.adapters.milky" in module
        or (
            (hasattr(type(bot), "get_group_list") or "get_group_list" in bot.__dict__)
            and (
                hasattr(type(bot), "get_group_member_list")
                or "get_group_member_list" in bot.__dict__
            )
        )
    )
    if not has_group_api:
        await clean_groups.finish("❌ 当前平台不支持群列表批量清理。")

    await clean_groups.send("⚠️ 开始清理低群人数群组...")
    api = cast(_GroupListAPI, bot)
    groups = await api.get_group_list()
    admins = _superuser_int_ids()
    left = skipped_admin = skipped_owner = failed = 0
    for group in groups:
        info = _extract_group_info(group)
        if info is None:
            continue
        group_id, group_name = info
        try:
            raw_members = await api.get_group_member_list(group_id=group_id)
            members: set[int] = {
                uid
                for member in raw_members
                if (uid := _extract_member_id(member)) is not None
            }
        except Exception as e:
            logger.error(f"⚠️ 获取群成员信息失败: {e!s}")
            failed += 1
            continue

        if len(members) < 20:
            admin_members = members & admins
            if len(admin_members) > 0:
                await clean_groups.send(
                    f"⚠️ 群组 {group_name} ({group_id}) 人数小于20,但有 {len(admin_members)} 个Bot管理员，跳过"
                )
                skipped_admin += 1
                continue
            if await is_group_owner(bot, group_id):
                await clean_groups.send(
                    f"⚠️ 群组 {group_name} ({group_id}) 人数小于20,但Bot是群主，跳过"
                )
                skipped_owner += 1
                continue
            await clean_groups.send(f"⚠️ 尝试退出群组{group_name}({group_id}).....")
            try:
                scope = Scope(platform=env.scope.platform, kind=GROUP, id=str(group_id))
                sender = resolve_sender(bot, scope, adapter=env.adapter or None)
                notice = (
                    "⚠️ 该群人数小于二十人！Bot将退出该群组。"
                    f"{f'如有疑问请加群{get_amrita_config().public_group}' if get_amrita_config().public_group else ''}。"
                )
                if sender is not None:
                    await sender.send_text(notice)
            except Exception as e:
                logger.error(f"⚠️ 发送退群通知失败: {e!s}")
            try:
                if await _leave_group(bot, group_id):
                    left += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"⚠️ 退出群组失败: {e!s}")
                failed += 1
    await clean_groups.finish(
        f"✅ 清理完成：退出 {left} 群，跳过（有管理员）{skipped_admin} 群，跳过（Bot为群主）{skipped_owner} 群，失败 {failed} 群"
    )
