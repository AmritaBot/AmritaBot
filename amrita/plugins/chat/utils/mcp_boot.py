"""MCP 服务加载：逐个隔离，单个服务失败不牵连其余服务与整体启动。

Core 的 ``ClientManager.initialize_this`` 在失败时只记一条日志，且失败发生在
``_load_this`` 注册到一半时，已注册的工具会留在工具池里——它们没有对应的
``name_to_clients`` 映射，被调用只会得到 "Tool not found"，看起来像是别处炸了。
本模块在失败后把这些半成品工具清理掉，并保证一个服务超时 / 抛异常不影响
同批其他服务，也不影响插件启动。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from amrita_core.tools.mcp import ClientManager
from exceptiongroup import BaseExceptionGroup
from nonebot import logger

#  单个 MCP 服务的初始化上限（秒）：stdio 服务拉起进程、远端服务建连都在此预算内
MCP_INIT_TIMEOUT = 30


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
    """撤掉上一次失败尝试注册到一半的工具。"""
    try:
        added = set(manager.tools_manager.get_tools()) - before
        for name in added:
            manager.tools_manager.remove_tool(name)
            manager.name_to_clients.pop(name, None)
    except Exception as e:
        #  清理本身失败也不能盖过原始错误，记一笔就放过
        logger.opt(exception=e).warning("清理 MCP 半成品工具失败")


async def load_mcp_servers(
    scripts: list[str],
    *,
    manager: ClientManager | None = None,
    timeout: float = MCP_INIT_TIMEOUT,
) -> MCPLoadReport:
    """逐个加载 MCP 服务，任一失败只记录并清理，不向上抛。"""
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
            tools = tuple(
                name
                for name, owner in manager.name_to_clients.items()
                if str(owner.server_script) == script
            )
            _record(script, tools, None)
            report.loaded.append(script)

    if report.failed:
        logger.warning(f"MCP 服务加载完成，部分失败：{report.summary()}")
    else:
        logger.info(f"MCP 服务加载完成：{report.summary()}")
    return report
