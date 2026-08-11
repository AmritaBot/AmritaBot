"""权限管理 API：权限组、用户权限、群组权限。"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

from amrita.plugins.perm.models import PermissionStorage
from amrita.plugins.perm.nodelib import Permissions

from ..main import app
from ..response import fail, ok


class PermGroupCreateSchema(BaseModel):
    name: str


class PermissionsUpdateSchema(BaseModel):
    permissions: str


@app.get("/api/permissions/groups")
async def list_perm_groups():
    """权限组列表。"""
    dt = PermissionStorage()
    # no_cache：WebUI 列表必须实时反映创建/删除（PermissionStorage 缓存由插件内部刷新）
    groups = await dt.get_all_perm_groups(no_cache=True)
    return ok(
        "success",
        data={
            "groups": [
                {
                    "name": group.group_name,
                    "permissions": Permissions(group.permissions).perm_str,
                }
                for group in groups
            ]
        },
    )


@app.post("/api/permissions/groups")
async def create_perm_group(data: PermGroupCreateSchema):
    """创建权限组。"""
    if not data.name:
        return fail(400, "权限组名称不能为空")
    dt = PermissionStorage()
    if await dt.permission_group_exists(data.name):
        return fail(400, "权限组已存在")
    try:
        await dt.create_permission_group(data.name)
    except Exception as e:
        return fail(500, str(e))
    return ok(f"权限组 {data.name} 创建成功")


@app.get("/api/permissions/groups/{name}")
async def get_perm_group(name: str):
    """权限组详情。"""
    dt = PermissionStorage()
    if not await dt.permission_group_exists(name):
        raise HTTPException(status_code=404, detail="权限组不存在")
    group = await dt.get_permission_group(name)
    return ok(
        "success",
        data={
            "name": name,
            "permissions": Permissions(group.permissions).permissions_str,
            # 权限组本身无「关联权限组」概念（关联只存在于成员↔组），
            # 保持响应契约完整（前端 permission_groups.join 需要数组）
            "permission_groups": [],
        },
    )


@app.post("/api/permissions/groups/{name}")
async def update_perm_group(name: str, data: PermissionsUpdateSchema):
    """更新权限组权限。"""
    try:
        perm = Permissions()
        perm.from_perm_str(data.permissions)
        dt = PermissionStorage()
        group_data = await dt.get_permission_group(name)
        group_data.permissions = perm.dump_data()
        await dt.update_permission_group(group_data)
        return ok("权限组权限已更新")
    except Exception as e:
        return fail(400, str(e))


@app.post("/api/permissions/groups/{name}/delete")
async def delete_perm_group(name: str):
    """删除权限组。"""
    dt = PermissionStorage()
    try:
        await dt.delete_permission_group(name)
    except Exception as e:
        return fail(500, str(e))
    return ok("权限组已删除")


@app.get("/api/permissions/users/{user_id}")
async def get_user_permissions(user_id: str):
    """用户权限详情。"""
    dt = PermissionStorage()
    user_data = await dt.get_member_permission(user_id, "user")
    perm = Permissions(user_data.permissions)
    groups = (
        await dt.get_member_related_permission_groups(user_id, "user")
    ).groups
    return ok(
        "success",
        data={
            "user_id": user_id,
            "permissions": perm.permissions_str,
            "permission_groups": groups,
        },
    )


@app.post("/api/permissions/users/{user_id}")
async def update_user_permissions(user_id: str, data: PermissionsUpdateSchema):
    """更新用户权限。"""
    try:
        dt = PermissionStorage()
        perm = Permissions()
        perm.from_perm_str(data.permissions)
        user_data = await dt.get_member_permission(user_id, "user")
        user_data.permissions = perm.dump_data()
        await dt.update_member_permission(user_data)
        return ok("用户权限已更新")
    except Exception as e:
        return fail(400, str(e))


@app.get("/api/permissions/group-scopes/{group_id}")
async def get_group_permissions(group_id: str):
    """群组权限详情。"""
    dt = PermissionStorage()
    group_data = await dt.get_member_permission(group_id, "group")
    perm = Permissions(group_data.permissions)
    groups = (
        await dt.get_member_related_permission_groups(group_id, "group")
    ).groups
    return ok(
        "success",
        data={
            "group_id": group_id,
            "permissions": perm.permissions_str,
            "permission_groups": groups,
        },
    )


@app.post("/api/permissions/group-scopes/{group_id}")
async def update_group_permissions(group_id: str, data: PermissionsUpdateSchema):
    """更新群组权限。"""
    try:
        dt = PermissionStorage()
        perm = Permissions()
        perm.from_perm_str(data.permissions)
        group_data = await dt.get_member_permission(group_id, "group")
        group_data.permissions = perm.dump_data()
        await dt.update_member_permission(group_data)
        return ok("群组权限已更新")
    except Exception as e:
        return fail(400, str(e))
