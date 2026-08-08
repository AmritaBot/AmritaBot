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
    "perm_group.permission",
    permission=is_lp_admin,
).handle()
async def lp_perm_group_permission(
    event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    args_list = args.extract_plain_text().strip().split()

    if len(args_list) < 2:
        await matcher.finish(
            "❌ 参数不足，需要：权限组ID 操作 [权限节点] [值]\n/lp.perm_group.permission <权限组ID> <操作:add|del|set|check|list> <权限节点> [值]"
        )

    id = args_list[0]
    operation = args_list[1]
    target = args_list[2] if len(args_list) >= 3 else ""
    value = args_list[3] if len(args_list) >= 4 else ""

    store = PermissionStorage()
    permission_group_data = await store.get_permission_group(id)
    if not permission_group_data:
        await matcher.finish(f"❌ 权限组 {id} 不存在")

    user_perm = Permissions(permission_group_data.permissions)
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
            msg_str = f"权限组权限列表：\n{user_perm.permissions_str}"
        case _:
            msg_str = "❌ 不支持的操作类型"

    permission_group_data.permissions = user_perm.dump_data()
    await store.update_permission_group(permission_group_data)
    await matcher.finish(msg_str)


# 父权限组操作相关指令
@command.command(
    "perm_group.parent",
    permission=is_lp_admin,
).handle()
async def lp_perm_group_parent(
    event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    args_list = args.extract_plain_text().strip().split()

    if len(args_list) < 3:
        await matcher.finish(
            "❌ 参数不足，需要：权限组ID 操作 权限组名\n/lp.perm_group.parent <权限组ID> <操作:add|del|set> <权限组名>"
        )

    id = args_list[0]
    operation = args_list[1]
    target = args_list[2]

    store = PermissionStorage()
    permission_group_data = await store.get_permission_group(id)
    if not permission_group_data:
        await matcher.finish(f"❌ 权限组 {id} 不存在")

    perm_target_data = (
        await store.get_permission_group(target)
        if await store.permission_group_exists(target)
        else None
    )
    if perm_target_data is None:
        await matcher.finish("❌ 权限组不存在")

    string_msg = "❌ 操作失败"

    match operation:
        case "add" | "del":
            # 修改继承关系
            group_perms = Permissions(perm_target_data.permissions)
            user_perms = Permissions(permission_group_data.permissions)

            for node, state in group_perms.data.items():
                if operation == "add" and not user_perms.check_permission(node):
                    user_perms.set_permission(node, state)
                elif operation == "del" and user_perms.check_permission(node):
                    user_perms.del_permission(node)
            permission_group_data.permissions = user_perms.dump_data()

            string_msg = (
                f"✅ 已{'添加' if operation == 'add' else '移除'}于继承组 {target}"
            )
        case "set":
            permission_group_data.permissions = (
                deepcopy(perm_target_data.permissions) or {}
            )
            string_msg = f"✅ 已覆盖为组 {target} 的权限"
        case _:
            string_msg = "❌ 不支持的操作类型"

    await store.update_permission_group(permission_group_data)
    await matcher.finish(string_msg)


# 权限组管理相关指令
@command.command(
    "perm_group.to",
    permission=is_lp_admin,
).handle()
async def lp_perm_group_to(
    event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    args_list = args.extract_plain_text().strip().split()

    if len(args_list) < 2:
        await matcher.finish(
            "❌ 参数不足，需要：操作 权限组ID\n/lp.perm_group.to <操作:create|remove> <权限组ID>"
        )

    id = args_list[1]  # 权限组ID
    operation = args_list[0]  # 操作

    store = PermissionStorage()
    if any(name.value == id for name in DefaultPermissionGroupsEnum):
        await matcher.finish("❌ 默认权限组不允许被删除")
    if operation == "create":
        # 检查权限组是否已存在
        if await store.permission_group_exists(id):
            await matcher.finish("❌ 权限组已存在")
        # 创建新的权限组
        new_group_data = await store.get_permission_group(id)
        await store.update_permission_group(new_group_data)
        await matcher.finish("✅ 权限组创建成功")
    elif operation == "remove":
        # 检查权限组是否存在
        if not await store.permission_group_exists(id):
            await matcher.finish("❌ 权限组不存在")
        await store.delete_permission_group(id)
        await matcher.finish("✅ 权限组删除成功")
    else:
        await matcher.finish("❌ 操作错误，仅支持 create/remove")


@command.command("perm_group.list", permission=is_lp_admin).handle()
async def _(matcher: Matcher):
    perm_groups = await PermissionStorage().get_all_perm_groups()
    await matcher.finish(
        "权限组列表：\n" + "".join([f"{group.group_name}\n" for group in perm_groups])
    )


# 运行进入点
@command.command(
    "perm_group",
    permission=is_lp_admin,
    state=MatcherData(
        name="lp权限组配置",
        description="配置权限组权限",
        usage="/lp.perm_group.[to|parent|permission|list]",
        show_if="lp.admin",
    ).model_dump(),
).handle()
async def lp_perm_group(
    event: MessageEvent,
    matcher: Matcher,
):
    await matcher.send(
        "请使用 /lp.perm_group.[to|parent|permission|list] 指令进行操作。"
    )
