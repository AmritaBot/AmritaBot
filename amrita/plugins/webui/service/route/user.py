# 重构
from __future__ import annotations

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from amrita.plugins.manager.blacklist.black import BL_Manager
from amrita.plugins.perm.models import PermissionStorage
from amrita.plugins.perm.nodelib import Permissions
from amrita.plugins.webui.service.response import fail, ok

from ..main import TemplatesManager, app
from ..sidebar import SideBarManager


@app.get("/user/blacklist", response_class=HTMLResponse)
async def _(request: Request):
    side_bar = SideBarManager().get_sidebar_dump()

    for bar in side_bar:
        if bar["name"] == "用户管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child["name"] == "黑名单管理":
                    child["active"] = True
            break
    data = await BL_Manager.get_full_blacklist()
    response = TemplatesManager().TemplateResponse(
        request,
        "blacklist.html",
        {
            "sidebar_items": side_bar,
            "group_blacklist": [
                {
                    "id": k,
                    "reason": v.reason,
                    "added_time": v.time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for k, v in data["group"].items()
            ],
            "user_blacklist": [
                {
                    "id": k,
                    "reason": v.reason,
                    "added_time": v.time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for k, v in data["private"].items()
            ],
        },
    )
    return response


@app.get("/users/permissions", response_class=HTMLResponse)
async def permissions_page(request: Request):
    side_bar = SideBarManager().get_sidebar_dump()
    dt = PermissionStorage()
    for bar in side_bar:
        if bar["name"] == "用户管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child["name"] == "权限管理":
                    child["active"] = True
            break

    # 获取所有权限组
    permission_groups = []
    groups = await dt.get_all_perm_groups()
    for group in groups:
        group_name = group.group_name
        group_data = Permissions(group.permissions)
        permission_groups.append(
            {
                "name": group_name,
                "permissions": group_data.perm_str,
            }
        )

    return TemplatesManager().TemplateResponse(
        request,
        "permissions.html",
        {
            "sidebar_items": side_bar,
            "permission_groups": permission_groups,
        },
    )


@app.post("/api/users/permissions/perm_group/delete", response_class=JSONResponse)
async def delete_perm_group(request: Request):
    group_name = (await request.json()).get("group_name")
    if not group_name:
        return fail(400, "Invalid request")
    dt = PermissionStorage()
    try:
        await dt.delete_permission_group(group_name)
    except Exception as e:
        return fail(500, str(e))
    return ok("权限组已删除")


@app.get("/users/permissions/create_perm_group", response_class=HTMLResponse)
async def create_perm_group_page(request: Request):
    side_bar = SideBarManager().get_sidebar_dump()

    for bar in side_bar:
        if bar["name"] == "用户管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child["name"] == "权限管理":
                    child["active"] = True
            break

    return TemplatesManager().TemplateResponse(
        request,
        "create_perm_group.html",
        {
            "sidebar_items": side_bar,
        },
    )


@app.get("/users/permissions/user/{user_id}", response_class=HTMLResponse)
async def user_permissions_page(request: Request, user_id: str):
    side_bar = SideBarManager().get_sidebar_dump()

    for bar in side_bar:
        if bar["name"] == "用户管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child["name"] == "权限管理":
                    child["active"] = True
            break

    # 获取用户权限数据
    user_data = await PermissionStorage().get_member_permission(user_id, "user")
    user_permission_groups: list[str] = (
        await PermissionStorage().get_member_related_permission_groups(user_id, "user")
    ).groups
    perm = Permissions(user_data.permissions)
    permissions_str = perm.permissions_str

    return TemplatesManager().TemplateResponse(
        request,
        "user_permissions.html",
        {
            "sidebar_items": side_bar,
            "user_id": user_id,
            "user_data": {
                "permissions": permissions_str,
                "permission_groups": user_permission_groups,
            },
        },
    )


@app.get("/users/permissions/group/{group_id}", response_class=HTMLResponse)
async def group_permissions_page(request: Request, group_id: str):
    side_bar = SideBarManager().get_sidebar_dump()

    for bar in side_bar:
        if bar["name"] == "用户管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child["name"] == "权限管理":
                    child["active"] = True
            break

    # 获取群组权限数据
    group_data = await PermissionStorage().get_member_permission(group_id, "group")
    permission_groups = await PermissionStorage().get_member_related_permission_groups(
        group_id, "group"
    )
    perm = Permissions(group_data.permissions)
    permissions_str = perm.permissions_str

    return TemplatesManager().TemplateResponse(
        request,
        "group_permissions.html",
        {
            "sidebar_items": side_bar,
            "group_id": group_id,
            "group_data": {
                "permissions": permissions_str,
                "permission_groups": permission_groups.groups,
            },
        },
    )


@app.get("/users/permissions/perm_group/{group_name}", response_class=HTMLResponse)
async def perm_group_permissions_page(request: Request, group_name: str):
    side_bar = SideBarManager().get_sidebar_dump()

    for bar in side_bar:
        if bar["name"] == "用户管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child["name"] == "权限管理":
                    child["active"] = True
            break

    # 获取权限组权限数据
    if not await PermissionStorage().permission_group_exists(group_name):
        raise HTTPException(status_code=404, detail="权限组不存在")

    perm = Permissions(
        (await PermissionStorage().get_permission_group(group_name)).permissions
    )

    permissions_str = perm.permissions_str

    return TemplatesManager().TemplateResponse(
        request,
        "perm_group_permissions.html",
        {
            "sidebar_items": side_bar,
            "group_name": group_name,
            "permissions": permissions_str,
        },
    )


@app.post("/api/users/permissions/user/{user_id}")
async def update_user_permissions(user_id: str, permissions: str = Form(...)):
    try:
        dt = PermissionStorage()
        user_data = await dt.get_member_permission(user_id, "user")
        perm = Permissions()
        perm.from_perm_str(permissions)
        user_data.permissions = perm.dump_data()
        await dt.update_member_permission(user_data)

        return ok("用户权限已更新")
    except Exception as e:
        return fail(400, str(e))


@app.post("/api/users/permissions/group/{group_id}")
async def update_group_permissions(group_id: str, permissions: str = Form(...)):
    try:
        st = PermissionStorage()
        perm = Permissions()
        perm.from_perm_str(permissions)
        group_data = await st.get_member_permission(group_id, "group")
        group_data.permissions = perm.dump_data()

        await st.update_member_permission(group_data)
        return ok("群组权限已更新")
    except Exception as e:
        return fail(400, str(e))


@app.post("/api/users/permissions/perm_group/{group_name}")
async def update_perm_group_permissions(group_name: str, permissions: str = Form(...)):
    try:
        perm = Permissions()
        st = PermissionStorage()
        perm.from_perm_str(permissions)
        permissions_data = perm.dump_data()
        data = await st.get_permission_group(group_name)
        data.permissions = permissions_data
        await st.update_permission_group(data)
        return ok("权限组权限已更新")
    except Exception as e:
        return fail(400, str(e))
