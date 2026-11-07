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

    #  Core 的 initialize_scripts_all 会被单个坏服务打断整个启动，这里改成逐个加载
    function_config = core_config.function_config
    mcp_scripts = (
        list(function_config.agent_mcp_server_scripts)
        if function_config.agent_mcp_client_enable
        else []
    )

    #  装配期间临时清空并立即还原，否则后续 save_config 会把空列表写回磁盘
    saved_scripts = function_config.agent_mcp_server_scripts
    function_config.agent_mcp_server_scripts = []
    try:
        set_config(core_config)
        await load_amrita()
    finally:
        function_config.agent_mcp_server_scripts = saved_scripts

    if mcp_scripts:
        await load_mcp_servers(mcp_scripts)
