"""启动依赖：AmritaCore 运行时装配"""

from __future__ import annotations

from amrita_core import load_amrita, set_config

from ..config import config_manager
from ..utils.mcp_boot import load_mcp_servers


async def setup_core_runtime() -> None:
    """加载并装配 AmritaCore 运行时

    读取聊天插件配置，注入 AmritaCore 全局配置并加载其运行时。
    """
    config = await config_manager.safe_get_config()
    core_config = config.core

    #  MCP 由本插件逐个加载：Core 的 `initialize_scripts_all` 会把单个服务的
    #  异常直接抛给调用方，服务列表里有一条坏的就整个启动失败。这里先把列表
    #  摘出来交给 `load_mcp_servers`，失败只记日志、不影响其余服务与启动。
    function_config = core_config.function_config
    mcp_scripts = (
        list(function_config.agent_mcp_server_scripts)
        if function_config.agent_mcp_client_enable
        else []
    )

    #  只在 Core 装配期间清空，装配完立即还原：配置对象是活的，
    #  留空会被后续的 save_config 写回磁盘，把服务列表抹掉
    saved_scripts = function_config.agent_mcp_server_scripts
    function_config.agent_mcp_server_scripts = []
    try:
        set_config(core_config)
        await load_amrita()
    finally:
        function_config.agent_mcp_server_scripts = saved_scripts

    if mcp_scripts:
        await load_mcp_servers(mcp_scripts)
