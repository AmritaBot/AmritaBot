"""LitePerm 用户权限配置子命令 ``/lp.user.*``。"""

from __future__ import annotations

from copy import deepcopy

from nonebot.matcher import Matcher
from nonebot_plugin_alconna import Match

from amrita.platform.di import OptionalEnvelopeNBDep
from amrita.plugins.menu.models import MatcherData

from ..API.admin import is_lp_admin
from ..command_manager import command
from ..identity import DEFAULT_PLATFORM, resolve_member_id
from ..models import (
    DefaultPermissionGroupsEnum,
    PermissionStorage,
)
from ..nodelib import Permissions


@command.command(
    "user.permission",
    with_params=True,
    permission=is_lp_admin,
).handle()
async def lp_user_permission(
    matcher: Matcher, params: Match[tuple[str, ...]], env: OptionalEnvelopeNBDep
):
    args_list = list(params.result) if params.available else []

    if len(args_list) < 3:
        await matcher.finish(
            "❌ 参数不足，需要：用户ID 操作 [权限节点] [值]\n/lp.user.permission <用户ID> <操作:add|del|set|check|list> <权限节点> [值]"
        )

    platform = env.actor.platform if env is not None else DEFAULT_PLATFORM
    id = resolve_member_id(args_list[0], "user", default_platform=platform)
    operation = args_list[1]
    target = args_list[2] if len(args_list) >= 3 else ""
    value = args_list[3] if len(args_list) >= 4 else ""

    store = PermissionStorage()
    user_data = await store.get_member_permission(id, "user")
    if not user_data:
        await matcher.finish(f"❌ 用户 {id} 不存在")

    user_perm = Permissions(user_data.permissions)
    msg_str = ""

    match operation:
        case "del":
            if not target:
                await matcher.finish("❌ 请指定权限节点")
            user_perm.del_permission(target)
            msg_str = f"✅ 已删除权限节点 {target}"
        case "set":
            if not target:
                await matcher.finish("❌ 请指定权限节点")
            if value.lower() not in ("true", "false"):
                await matcher.finish("❌ 值必须是 true/false")
            user_perm.set_permission(target, value == "true")
            msg_str = f"✅ 已设置 {target} : {value}"
        case "check":
            if not target:
                await matcher.finish("❌ 请指定权限节点")
            msg_str = (
                "✅ 持有该权限"
                if user_perm.check_permission(target)
                else "❌ 未持有该权限"
            )
        case "list":
            msg_str = f"用户权限列表：\n{user_perm.permissions_str}"
        case _:
            msg_str = "❌ 不支持的操作类型"

    user_data.permissions = user_perm.dump_data()
    await PermissionStorage().update_member_permission(user_data)
    await matcher.finish(msg_str)


@command.command(
    "user.parent",
    with_params=True,
    permission=is_lp_admin,
).handle()
async def lp_user_parent(
    matcher: Matcher, params: Match[tuple[str, ...]], env: OptionalEnvelopeNBDep
):
    args_list = list(params.result) if params.available else []

    if len(args_list) < 3:
        await matcher.finish(
            "❌ 参数不足，需要：用户ID 操作 权限组名\n/lp.user.parent <用户ID> <操作:add|del|set> <权限组名>"
        )

    platform = env.actor.platform if env is not None else DEFAULT_PLATFORM
    id = resolve_member_id(args_list[0], "user", default_platform=platform)
    operation = args_list[1]
    target = args_list[2]

    store = PermissionStorage()
    user_data = await store.get_member_permission(id, "user")
    if not user_data:
        await matcher.finish(f"❌ 用户 {id} 不存在")

    perm_target_data = (
        await store.get_permission_group(target)
        if await store.permission_group_exists(target)
        else None
    )
    if perm_target_data is None:
        await matcher.finish("❌ 权限组不存在")

    string_msg = ""

    match operation:
        case "add" | "del":
            group_perms = Permissions(perm_target_data.permissions)
            user_perms = Permissions(user_data.permissions)

            for node, state in group_perms.data.items():
                if operation == "add" and not user_perms.check_permission(node):
                    user_perms.set_permission(node, state)
                elif operation == "del" and user_perms.check_permission(node):
                    user_perms.del_permission(node)
            user_data.permissions = user_perms.dump_data()

            string_msg = (
                f"✅ 已{'添加' if operation == 'add' else '移除'}继承组 {target}"
            )
        case "set":
            user_data.permissions = deepcopy(perm_target_data.permissions) or {}
            string_msg = f"✅ 已覆盖为组 {target} 的权限"
        case _:
            string_msg = "❌ 未知操作类型"

    await PermissionStorage().update_member_permission(user_data)
    await matcher.finish(string_msg)


@command.command(
    "user.perm_group",
    with_params=True,
    permission=is_lp_admin,
).handle()
async def lp_user_perm_group(
    matcher: Matcher, params: Match[tuple[str, ...]], env: OptionalEnvelopeNBDep
):
    args_list = list(params.result) if params.available else []

    if len(args_list) < 3:
        await matcher.finish(
            "❌ 参数不足，需要：用户ID 操作 权限组名\n/lp.user.perm_group <用户ID> <操作:add|del> <权限组名>"
        )

    platform = env.actor.platform if env is not None else DEFAULT_PLATFORM
    id = resolve_member_id(args_list[0], "user", default_platform=platform)
    operation = args_list[1]
    target = args_list[2]

    store = PermissionStorage()
    msg_str = ""
    if any(name.value == target for name in DefaultPermissionGroupsEnum):
        await matcher.finish("不允许操作默认权限组")
    if operation == "add":
        if not await store.is_member_in_permission_group(id, "user", target):
            if not await store.permission_group_exists(target):
                await matcher.finish(f"❌ 权限组 {target} 不存在")
            await store.get_member_permission(id, "user")
            await store.add_member_related_permission_group(id, "user", target)
            msg_str = f"✅ 成功添加权限组 {target}"
        else:
            msg_str = f"❌ 用户已存在于权限组 {target}"
    elif operation == "del":
        if await store.is_member_in_permission_group(id, "user", target):
            await store.del_member_related_permission_group(id, "user", target)
            msg_str = f"✅ 将用户从权限组 {target} 移除成功"
        else:
            await matcher.finish(f"❌ {target} 不存在该已关系的用户")
    else:
        await matcher.finish("❌ 不支持的操作类型，仅支持 add/del")

    await matcher.finish(msg_str)


@command.command(
    "user",
    permission=is_lp_admin,
    state=MatcherData(
        name="lp用户权限配置",
        description="配置特定用户权限",
        usage=[
            "/lp.user.permission <用户ID> <add|del|set|check|list> <权限节点> [值]",
            "/lp.user.parent <用户ID> <add|del|set> <权限组名>",
            "/lp.user.perm_group <用户ID> <add|del> <权限组名>",
        ],
        show_if="lp.admin",
    ).model_dump(),
).handle()
async def lp_user(
    matcher: Matcher,
):
    await matcher.finish(
        "请使用以下指令操作：\n"
        "/lp.user.permission <用户ID> <add|del|set|check|list> <权限节点> [值]\n"
        "/lp.user.parent <用户ID> <add|del|set> <权限组名>\n"
        "/lp.user.perm_group <用户ID> <add|del> <权限组名>"
    )
