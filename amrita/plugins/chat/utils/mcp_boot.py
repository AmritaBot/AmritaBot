"""MCP 服务的加载与重连：逐个隔离，单个服务失败不牵连其余服务与整体启动。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from amrita_core.tools.mcp import ClientManager
from exceptiongroup import BaseExceptionGroup
from nonebot import logger

from ..config import config_manager

#  单个 MCP 服务的初始化上限（秒）：stdio 服务拉起进程、远端服务建连都在此预算内
MCP_INIT_TIMEOUT = 30

#  增删改查共用一把锁：并发操作会在「连上新的」与「写盘」之间互相打乱
_operation_lock = asyncio.Lock()


def operation_lock() -> asyncio.Lock:
    """返回 MCP 增删改重载的进程内互斥锁。"""
    return _operation_lock


def configured_scripts() -> list[str]:
    """返回配置里生效的 MCP 服务脚本列表，未开启 MCP 时为空。"""
    function_config = config_manager.ins_config.core.function_config
    if not function_config.agent_mcp_client_enable:
        return []
    return list(function_config.agent_mcp_server_scripts)


@dataclass
class MCPServerState:
    """一个 MCP 服务的运行时状态。

    ``id`` 是进程内稳定的标识：同一脚本重载后沿用同一个 id，删除再添加才会换。
    配置里可能没有这条记录（例如添加时保存失败），但状态一定有，删除与展示都
    以它为准，不再回配置里找一个可能不存在的项。
    """

    id: str
    script: str
    status: Literal["connected", "error"]
    tools: tuple[str, ...] = ()
    error: str | None = None


#  运行时状态表：id -> 状态；script -> id 便于重复加载时复用同一标识
_states: dict[str, MCPServerState] = {}
_script_ids: dict[str, str] = {}
_next_state_id = 1


def list_states() -> list[MCPServerState]:
    """按加载顺序返回全部 MCP 服务状态。"""
    return list(_states.values())


def find_state(ref: str) -> MCPServerState | None:
    """按 id 或脚本地址查找状态。"""
    if ref in _states:
        return _states[ref]
    state_id = _script_ids.get(ref)
    return _states.get(state_id) if state_id else None


def remove_state(ref: str) -> MCPServerState | None:
    """从状态表移除一条记录。"""
    state = find_state(ref)
    if state is None:
        return None
    _states.pop(state.id, None)
    _script_ids.pop(state.script, None)
    return state


def _record(script: str, tools: tuple[str, ...], error: str | None) -> MCPServerState:
    """写入或更新一个服务的状态，脚本未变时沿用原 id。"""
    global _next_state_id
    state_id = _script_ids.get(script)
    if state_id is None:
        state_id = f"mcp{_next_state_id}"
        _next_state_id += 1
        _script_ids[script] = state_id
    state = MCPServerState(
        id=state_id,
        script=script,
        status="error" if error else "connected",
        tools=tools,
        error=error,
    )
    _states[state_id] = state
    return state


@dataclass
class MCPLoadReport:
    """一批 MCP 服务的加载结果。"""

    loaded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        """一行摘要，供命令与日志使用。"""
        text = f"成功 {len(self.loaded)} 个，失败 {len(self.failed)} 个"
        if self.failed:
            text += "：" + "；".join(f"{s}（{e}）" for s, e in self.failed)
        return text


def _describe(exc: BaseException) -> str:
    """把异常压成一句可读原因，异常组展开成子项。"""
    if isinstance(exc, BaseExceptionGroup):
        return "；".join(_describe(item) for item in exc.exceptions)
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _discard_partial(manager: ClientManager, before: set[str]) -> None:
    """撤掉本次失败尝试留在工具池里、没有路由映射的幽灵工具。

    只删「快照之后新出现且没有 ``name_to_clients`` 映射」的工具：并发的另一次
    加载已注册成功的工具带着映射，不会被误删。
    """
    try:
        added = set(manager.tools_manager.get_tools()) - before
        for name in added - set(manager.name_to_clients):
            manager.tools_manager.remove_tool(name)
            if remap := manager.tools_remapping.pop(name, None):
                manager.reversed_remappings.pop(remap, None)
    except Exception as e:
        #  清理本身失败也不能盖过原始错误，记一笔就放过
        logger.opt(exception=e).warning("清理 MCP 半成品工具失败")


def _owned_tools(manager: ClientManager, script: str) -> tuple[str, ...]:
    """收集当前映射到某个脚本名下的工具名。"""
    return tuple(
        name
        for name, owner in manager.name_to_clients.items()
        if str(owner.server_script) == script
    )


async def load_mcp_servers(
    scripts: list[str],
    *,
    manager: ClientManager | None = None,
    timeout: float = MCP_INIT_TIMEOUT,
) -> MCPLoadReport:
    """逐个加载 MCP 服务，单个服务的失败或超时不影响其余服务。

    Args:
        scripts: 服务脚本列表，可以是本地路径、命令或 URL；调用方负责去重。
        manager: 复用的 ``ClientManager``，省略时取全局单例。
        timeout: 单个服务的初始化上限（秒），超时按失败处理并清理半成品工具。

    Returns:
        ``MCPLoadReport``：成功与失败的脚本及原因；同时写入运行时状态表，
        失败的服务以 ``error`` 状态留存，供列表与后续重载使用。
    """
    report = MCPLoadReport()
    if not scripts:
        return report

    manager = manager or ClientManager()
    for script in scripts:
        before = set(manager.tools_manager.get_tools())
        try:
            #  用 wait_for 而非 asyncio.timeout：后者是 3.11 才有的，本包仍支持 3.10
            await asyncio.wait_for(
                manager.initialize_this(script, fail_then_raise=True), timeout
            )
        except (TimeoutError, asyncio.TimeoutError):
            _discard_partial(manager, before)
            reason = f"初始化超时（{timeout:g} 秒）"
            logger.warning(f"MCP Server@{script} {reason}，已跳过")
            _record(script, (), reason)
            report.failed.append((script, reason))
        except asyncio.CancelledError:
            #  取消属于正常收尾信号，清理后原样上抛
            _discard_partial(manager, before)
            raise
        except (Exception, BaseExceptionGroup) as e:
            _discard_partial(manager, before)
            reason = _describe(e)
            logger.error(f"MCP Server@{script} 加载失败：{reason}")
            _record(script, (), reason)
            report.failed.append((script, reason))
        else:
            _record(script, _owned_tools(manager, script), None)
            report.loaded.append(script)

    if report.failed:
        logger.warning(f"MCP 服务加载完成，部分失败：{report.summary()}")
    else:
        logger.info(f"MCP 服务加载完成：{report.summary()}")
    return report


async def reload_mcp_servers(
    scripts: list[str],
    *,
    manager: ClientManager | None = None,
    timeout: float = MCP_INIT_TIMEOUT,
    reset_remapping: bool = False,
) -> MCPLoadReport:
    """断开现有连接后按脚本列表重连，失败的服务保留状态并带原因。

    Args:
        scripts: 重载后应当活着的服务列表，不在其中的客户端会被断开。
        manager: 复用的 ``ClientManager``，省略时取全局单例。
        timeout: 单个服务的断开与初始化上限（秒）。
        reset_remapping: 是否丢弃工具名重映射表，深度重载时使用。

    Returns:
        ``MCPLoadReport``：逐个重连的结果。
    """
    manager = manager or ClientManager()
    if reset_remapping:
        manager.tools_remapping.clear()
        manager.reversed_remappings.clear()

    teardown_failed: dict[str, str] = {}
    for cl in list(manager.clients):
        script = str(cl.server_script)
        try:
            await manager.unregister_client(cl.server_script)
            await asyncio.wait_for(cl.close_no_wait(), timeout)
        except Exception as e:
            #  一个服务拆不干净也不能拦住其余服务的重连
            teardown_failed[script] = _describe(e)
            logger.opt(exception=e).warning(
                f"MCP Server@{script} 断开失败，继续重连其余服务"
            )

    targets = list(dict.fromkeys(scripts))
    for state in list_states():
        if state.script not in targets:
            remove_state(state.id)
    report = await load_mcp_servers(targets, manager=manager, timeout=timeout)
    for script, reason in teardown_failed.items():
        if script in report.loaded:
            #  旧连接没拆干净：新连接虽然起来了，但可能同时存在两个，不能报成功
            report.loaded.remove(script)
            report.failed.append((script, f"旧连接断开失败：{reason}"))
    return report


def restore_state_id(script: str, state_id: str) -> None:
    """把某个脚本重新绑定回指定 id，供回滚场景避免标识漂移。"""
    state = find_state(script)
    if state is None or state.id == state_id:
        return
    _states.pop(state.id, None)
    _states[state_id] = MCPServerState(
        id=state_id,
        script=script,
        status=state.status,
        tools=state.tools,
        error=state.error,
    )
    _script_ids[script] = state_id
