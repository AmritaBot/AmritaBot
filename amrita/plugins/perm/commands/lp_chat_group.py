from copy import deepcopy

from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.plugins.menu.models import MatcherData

from ..API.admin import is_lp_admin
from ..command_manager import command
from ..models import (
    DefaultPermissionGroupsEnum,
    PermissionStorage,
)
from ..nodelib import Permissions


# 权限节点操作相关指令
@command.command(
    "chat_group.permission",
    permission=is_lp_admin,
).handle()
async def lp_group_permission(
    event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    args_list = args.extract_plain_text().strip().split()

    if len(args_list) < 2:
        await matcher.finish(
            "❌ 参数不足，需要：群号 操作 [权限节点] [值]\n/lp.chat_group.permission <群号> <操作:add|del|set|check|list> <权限节点> [值]"
        )

    id = args_list[0]
    operation = args_list[1]
    target = args_list[2] if len(args_list) >= 3 else ""
    value = args_list[3] if len(args_list) >= 4 else ""

    store = PermissionStorage()
    group_data = await store.get_member_permission(id, "group")
    group_perm = Permissions(group_data.permissions)
    msg_str = ""

    match operation:
        case "del":
            if not target:
                await matcher.finish("❌ 请指定权限节点")
            group_perm.del_permission(target)
            msg_str = f"✅ 已删除权限节点 {target}"
        case "set":
            if not target:
                await matcher.finish("❌ 请指定权限节点")
            if value.lower() not in ("true", "false"):
                await matcher.finish("❌ 值必须是 true/false")
            group_perm.set_permission(target, value == "true")
            msg_str = f"✅ 已设置 {target} : {value}"
        case "check":
            if not target:
                await matcher.finish("❌ 请指定权限节点")
            msg_str = (
                "✅ 持有该权限"
                if group_perm.check_permission(target)
                else "❌ 未持有该权限"
            )
        case "list":
            msg_str = f"群聊权限列表：\n{group_perm.permissions_str}"
        case _:
            msg_str = "❌ 不支持的操作类型"

    group_data.permissions = group_perm.dump_data()
    await PermissionStorage().update_member_permission(group_data)
    await matcher.finish(msg_str)


# 父权限组操作相关指令
@command.command(
    "chat_group.parent",
    permission=is_lp_admin,
).handle()
async def lp_group_parent(
    event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    args_list = args.extract_plain_text().strip().split()

    if len(args_list) < 3:
        await matcher.finish(
            "❌ 参数不足，需要：群号 操作 权限组名\n/lp.chat_group.parent <群号> <操作:add|del|set> <权限组名>"
        )

    id = args_list[0]
    operation = args_list[1]
    target = args_list[2]

    store = PermissionStorage()
    group_data = await store.get_member_permission(id, "group")
    if not group_data:
        await matcher.finish(f"❌ 群组 {id} 不存在")

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
            # 修改继承关系
            perm_group_perms = Permissions(perm_target_data.permissions)
            group_perms = Permissions(group_data.permissions)

            for node, state in perm_group_perms.data.items():
                if operation == "add" and not group_perms.check_permission(node):
                    group_perms.set_permission(node, state)
                elif operation == "del" and group_perms.check_permission(node):
                    group_perms.del_permission(node)
            group_data.permissions = group_perms.dump_data()

            string_msg = (
                f"✅ 已{'添加' if operation == 'add' else '移除'}继承组 {target}"
            )
        case "set":
            group_data.permissions = deepcopy(perm_target_data.permissions) or {}
            string_msg = f"✅ 已完全Copy覆盖为组 {target} 的权限"
        case _:
            string_msg = "❌ 不支持的操作类型"

    await PermissionStorage().update_member_permission(group_data)
    await matcher.finish(string_msg)


# 权限组关系操作相关指令
@command.command(
    "chat_group.perm_group",
    permission=is_lp_admin,
).handle()
async def lp_group_perm_group(
    event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    args_list = args.extract_plain_text().strip().split()

    if len(args_list) < 3:
        await matcher.finish(
            "❌ 参数不足，需要：群号 操作 权限组名\n/lp.chat_group.perm_group <群号> <操作:add|del> <权限组名>"
        )

    id = args_list[0]
    operation = args_list[1]
    target = args_list[2]

    store = PermissionStorage()
    msg_str = ""
    if any(name.value == target for name in DefaultPermissionGroupsEnum):
        await matcher.finish("❌ 不允许操作默认权限组")

    if operation == "add":
        if await store.permission_group_exists(target):
            await store.add_member_related_permission_group(id, "group", target)
            msg_str = f"✅ 成功添加权限组 {target}"
        else:
            await matcher.finish(f"❌ 权限组 {target} 不存在")
    elif operation == "del":
        if await store.is_member_in_permission_group(id, "group", target):
            await store.del_member_related_permission_group(id, "group", target)
            msg_str = f"✅ 删除权限组关系 `{target}` 成功"
        else:
            await matcher.finish(f"❌ 目标不在权限组： `{target}`")
    else:
        await matcher.finish("❌ 不支持的操作类型，仅支持 add/del")

    await matcher.finish(msg_str)


# 运行进入点
@command.command(
    "chat_group",
    permission=is_lp_admin,
    state=MatcherData(
        name="lp聊群权限配置",
        description="配置特定群权限",
        usage="/lp.chat_group.[perm_group|parent|permission]",
        show_if="lp.admin",
    ).model_dump(),
).handle()
async def lp_group(
    event: MessageEvent,
    matcher: Matcher,
):
    await matcher.send(
        "请使用 /lp.chat_group.[perm_group|parent|permission] 指令进行操作。"
    )
