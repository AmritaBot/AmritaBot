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

from amrita_core.tools.mcp import ClientManager
from exceptiongroup import BaseExceptionGroup
from nonebot import logger

#  单个 MCP 服务的初始化上限（秒）：stdio 服务拉起进程、远端服务建连都在此预算内
MCP_INIT_TIMEOUT = 30


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
            report.failed.append((script, reason))
        except asyncio.CancelledError:
            #  取消属于正常收尾信号，清理后原样上抛
            _discard_partial(manager, before)
            raise
        except (Exception, BaseExceptionGroup) as e:
            _discard_partial(manager, before)
            reason = _describe(e)
            logger.error(f"MCP Server@{script} 加载失败：{reason}")
            report.failed.append((script, reason))
        else:
            report.loaded.append(script)

    if report.failed:
        logger.warning(f"MCP 服务加载完成，部分失败：{report.summary()}")
    else:
        logger.info(f"MCP 服务加载完成：{report.summary()}")
    return report
