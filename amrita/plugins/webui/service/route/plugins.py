"""插件管理 API。

读：已安装插件的六态合并视图、插件商店列表。
写：``enable`` / ``disable`` 只改配置；``install`` / ``uninstall`` 会跑 uv 并改配置。

写操作都起后台任务并立刻返回 ``task_id``，进度通过 WebSocket 的 ``plugins``
频道推流，或用 ``GET /api/bot/plugins/tasks/{task_id}`` 轮询兜底。

鉴权由 ``service/main.py`` 的中间件统一处理：``/api`` 未登录一律 401。
安装插件等同于在服务器上执行任意代码，因此这里的每个写接口都只对已登录的
WebUI 用户开放，前端还应加一道二次确认。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from amrita.utils.plugin_discovery import (
    invalidate_reverse_dependencies,
    protect_reason,
)
from amrita.utils.plugin_state import PluginSnapshot
from amrita.utils.pyproject_io import (
    PluginTarget,
    PyprojectNotFoundError,
    find_pyproject,
    modify_plugin_list,
)
from amrita.utils.uv import (
    FileSnapshot,
    UvCommandError,
    install_package,
    project_lockfiles,
    remove_package,
    summarize_uv_output,
    uv_available,
)

from ...API import broadcast_ws, register_ws_channel
from ..main import app
from ..plugin_source import (
    PluginSource,
    adapter_supported,
    available_adapters,
    get_plugin_store,
    incompatible_reason,
)
from ..plugin_tasks import PluginTask, get_task_manager
from ..response import fail, ok

logger = logging.getLogger(__name__)

#: 后台任务的强引用，防止被垃圾回收提前取消
_BACKGROUND: set[asyncio.Task[Any]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _plugins_channel_snapshot() -> dict[str, Any]:
    """订阅 plugins 频道时立即推送当前任务列表。"""
    tasks = get_task_manager().recent()
    return {
        "channel": "plugins",
        "data": {
            "tasks": [task.to_dict(with_lines=not task.finished) for task in tasks]
        },
    }


async def _on_plugin_task(task: PluginTask) -> None:
    """任务状态一变就广播到 plugins 频道。

    只推任务摘要与最新一行输出，完整输出由前端按需拉
    ``GET /api/bot/plugins/tasks/{id}``。
    """
    await broadcast_ws(
        "plugins",
        {
            "task": task.to_dict(with_lines=False),
            "line": task.lines[-1] if task.lines else None,
        },
    )


# 走 WebUI 官方扩展点声明频道；未声明的频道名会被 /amrita/ui/ws 忽略
register_ws_channel("plugins", _plugins_channel_snapshot)
get_task_manager().add_listener(_on_plugin_task)


def _project_root() -> Path:
    """定位项目根；找不到 ``pyproject.toml`` 时抛 :class:`PyprojectNotFoundError`。"""
    pyproject = find_pyproject()
    if pyproject is None:
        raise PyprojectNotFoundError("未找到 pyproject.toml")
    return pyproject.parent


class PluginActionRequest(BaseModel):
    """只改配置的请求体。"""

    module_name: str
    target: PluginTarget = "amrita"


class InstallRequest(BaseModel):
    """安装请求体。

    ``project_link`` 省略时会去商店里按 ``module_name`` 反查。
    """

    module_name: str
    project_link: str | None = None
    version: str | None = None
    target: PluginTarget | None = None


class UninstallRequest(BaseModel):
    """卸载请求体。

    ``purge=True`` 时额外执行 ``uv remove``；默认只从配置里移除。
    """

    module_name: str
    target: PluginTarget = "amrita"
    project_link: str | None = None
    purge: bool = False


@app.get("/api/bot/plugins")
async def list_plugins():
    """已安装插件的六态合并视图。"""
    try:
        snapshot = PluginSnapshot.capture()
    except PyprojectNotFoundError as exc:
        return fail(500, str(exc))

    entries = snapshot.entries()
    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry.state.value] = summary.get(entry.state.value, 0) + 1
    return ok(
        "success",
        data={
            "plugins": [entry.to_dict() for entry in entries],
            "summary": summary,
        },
    )


@app.get("/api/bot/plugins/store")
async def list_store(
    q: str | None = None,
    source: str | None = None,
    official: bool | None = None,
    tag: str | None = None,
    adapter: str | None = None,
    supported_only: bool = False,
    page: int = 1,
    size: int = 50,
    refresh: bool = False,
):
    """插件商店列表，带筛选与分页。

    返回的每条会附带 ``state``，前端据此决定显示「安装」还是「已安装」。
    """
    sources: list[PluginSource] | None = None
    if source and source != "all":
        sources = [
            cast("PluginSource", item)
            for item in source.split(",")
            if item in ("nonebot", "amrita")
        ]
        if not sources:
            return fail(400, "source 只能是 nonebot / amrita / all")

    store = get_plugin_store()
    items, total = await store.search(
        query=q,
        sources=sources,
        official=official,
        tag=tag,
        adapter=adapter,
        supported_only=supported_only,
        page=page,
        size=size,
        force=refresh,
    )

    hidden_by_adapter = 0
    if supported_only:
        # 同一组筛选条件、只是不按适配器筛，用来算出这个开关究竟藏了多少条
        _, total_without_adapter_filter = await store.search(
            query=q,
            sources=sources,
            official=official,
            tag=tag,
            adapter=adapter,
            supported_only=False,
            page=1,
            size=1,
        )
        hidden_by_adapter = max(0, total_without_adapter_filter - total)

    try:
        snapshot = PluginSnapshot.capture()
    except PyprojectNotFoundError:
        snapshot = None

    adapters = available_adapters()
    payload: list[dict[str, Any]] = []
    for item in items:
        data = item.to_dict()
        data["state"] = (
            snapshot.state_of(item.module_name).value if snapshot is not None else None
        )
        reason = incompatible_reason(item.requires) if item.requires else None
        data["compatible"] = reason is None
        data["incompatible_reason"] = reason
        data["supported_by_current"] = adapter_supported(
            item.supported_adapters, adapters
        )
        payload.append(data)

    return ok(
        "success",
        data={
            "plugins": payload,
            "total": total,
            "hidden_by_adapter": hidden_by_adapter,
            "page": page,
            "size": size,
            "warnings": list(store.warnings),
            "adapters": [
                {"name": name, "module": module} for name, module in adapters.items()
            ],
        },
    )


@app.post("/api/bot/plugins/enable")
async def enable_plugin(payload: PluginActionRequest):
    """把插件写进 ``[tool.<target>].plugins``，重启后生效。"""
    module_name = payload.module_name.strip()
    if not module_name:
        return fail(400, "module_name 不能为空")
    try:
        changed = modify_plugin_list(module_name, target=payload.target)
    except PyprojectNotFoundError as exc:
        return fail(500, str(exc))
    except TypeError as exc:
        return fail(500, str(exc))
    return ok(
        "已写入配置，重启后生效" if changed else "配置未发生变化",
        data={"changed": changed, "module_name": module_name},
    )


@app.post("/api/bot/plugins/disable")
async def disable_plugin(payload: PluginActionRequest):
    """把插件从 ``[tool.<target>].plugins`` 移除，重启后不再加载。"""
    module_name = payload.module_name.strip()
    if not module_name:
        return fail(400, "module_name 不能为空")
    blocked = protect_reason(module_name)
    if blocked is not None:
        return fail(
            400,
            f"不能禁用 {module_name}：{blocked}",
            data={"module_name": module_name, "blocked_by": blocked},
        )
    try:
        changed = modify_plugin_list(module_name, target=payload.target, remove=True)
    except PyprojectNotFoundError as exc:
        return fail(500, str(exc))
    except TypeError as exc:
        return fail(500, str(exc))
    return ok(
        "已移出配置，重启后生效" if changed else "配置中本就没有这一条",
        data={"changed": changed, "module_name": module_name},
    )


async def _run_install(
    task: PluginTask, *, module_name: str, spec: str, target: PluginTarget
) -> None:
    """后台执行安装：先 uv add，成功后再写配置，任一步失败都还原文件。"""
    manager = get_task_manager()
    await manager.set_running(task)
    snapshot: FileSnapshot | None = None
    try:
        root = _project_root()
        snapshot = FileSnapshot.capture(project_lockfiles(root))

        async def on_line(line: str) -> None:
            await manager.append_line(task, line)

        await install_package(spec, cwd=root, on_line=on_line)
        modify_plugin_list(module_name, target=target)
        invalidate_reverse_dependencies()
    except Exception as exc:  # 后台任务必须兜住所有异常，否则会静默消失
        if snapshot is not None:
            with suppress(Exception):
                snapshot.restore()
        logger.exception("安装插件失败: %s", spec)
        message = (
            summarize_uv_output(exc.output)
            if isinstance(exc, UvCommandError)
            else f"{type(exc).__name__}: {exc}"
        )
        await manager.finish(task, error=message)
        return
    await manager.finish(task)


async def _run_uninstall(
    task: PluginTask,
    *,
    module_name: str,
    target: PluginTarget,
    project_link: str | None,
    purge: bool,
) -> None:
    """后台执行卸载：默认只改配置；``purge`` 时先跑 ``uv remove``。"""
    manager = get_task_manager()
    await manager.set_running(task)
    snapshot: FileSnapshot | None = None
    try:
        root = _project_root()
        snapshot = FileSnapshot.capture(project_lockfiles(root))

        async def on_line(line: str) -> None:
            await manager.append_line(task, line)

        if purge:
            if not project_link:
                raise ValueError(
                    "purge 需要提供 project_link（uv remove 用的是发行包名）"
                )
            await remove_package(project_link, cwd=root, on_line=on_line)
        modify_plugin_list(module_name, target=target, remove=True)
        invalidate_reverse_dependencies()
    except Exception as exc:  # 后台任务必须兜住所有异常，否则会静默消失
        if snapshot is not None:
            with suppress(Exception):
                snapshot.restore()
        logger.exception("卸载插件失败: %s", module_name)
        message = (
            summarize_uv_output(exc.output)
            if isinstance(exc, UvCommandError)
            else f"{type(exc).__name__}: {exc}"
        )
        await manager.finish(task, error=message)
        return
    await manager.finish(task)


@app.post("/api/bot/plugins/install")
async def install_plugin(payload: InstallRequest):
    """安装插件：``uv add`` + 写入配置。立即返回 ``task_id``。"""
    if not uv_available():
        return fail(500, "未找到 uv，无法安装插件")

    module_name = payload.module_name.strip()
    if not module_name:
        return fail(400, "module_name 不能为空")

    project_link = payload.project_link
    target = payload.target
    if project_link is None:
        store = get_plugin_store()
        match = next(
            (item for item in await store.entries() if item.module_name == module_name),
            None,
        )
        if match is None:
            return fail(404, f"商店里没有 {module_name}，请显式提供 project_link")
        project_link = match.project_link or match.module_name
        if target is None:
            target = match.target
    spec = f"{project_link}=={payload.version}" if payload.version else project_link

    task = get_task_manager().create(
        action="install",
        package=spec,
        module_name=module_name,
        target=target or "amrita",
    )
    _spawn(
        _run_install(
            task, module_name=module_name, spec=spec, target=target or "amrita"
        )
    )
    return ok("已开始安装", data={"task_id": task.id, "package": spec})


@app.post("/api/bot/plugins/uninstall")
async def uninstall_plugin(payload: UninstallRequest):
    """卸载插件：默认只从配置移除，``purge=True`` 时额外 ``uv remove``。"""
    module_name = payload.module_name.strip()
    if not module_name:
        return fail(400, "module_name 不能为空")
    blocked = protect_reason(module_name)
    if blocked is not None:
        return fail(
            400,
            f"不能卸载 {module_name}：{blocked}",
            data={"module_name": module_name, "blocked_by": blocked},
        )
    if payload.purge and not uv_available():
        return fail(500, "未找到 uv，无法执行彻底卸载")

    task = get_task_manager().create(
        action="uninstall",
        package=payload.project_link or module_name,
        module_name=module_name,
        target=payload.target,
    )
    _spawn(
        _run_uninstall(
            task,
            module_name=module_name,
            target=payload.target,
            project_link=payload.project_link,
            purge=payload.purge,
        )
    )
    return ok("已开始卸载", data={"task_id": task.id})


@app.get("/api/bot/plugins/tasks")
async def list_tasks():
    """最近的安装 / 卸载任务（不含输出明细）。"""
    manager = get_task_manager()
    return ok(
        "success",
        data={"tasks": [task.to_dict(with_lines=False) for task in manager.recent()]},
    )


@app.get("/api/bot/plugins/tasks/{task_id}")
async def get_task(task_id: str):
    """单个任务的完整状态与输出。"""
    task = get_task_manager().get(task_id)
    if task is None:
        return fail(404, "任务不存在或已被清理")
    return ok("success", data=task.to_dict())
