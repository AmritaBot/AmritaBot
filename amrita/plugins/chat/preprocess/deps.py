"""启动依赖：AmritaCore 运行时装配"""

from __future__ import annotations

from amrita_core import load_amrita, set_config

from ..config import config_manager


async def setup_core_runtime() -> None:
    """加载并装配 AmritaCore 运行时

    读取聊天插件配置，注入 AmritaCore 全局配置并加载其运行时。
    """
    config = await config_manager.safe_get_config()
    core_config = config.core
    set_config(core_config)
    await load_amrita()
