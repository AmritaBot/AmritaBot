"""插件启动预处理

- startup.py: NoneBot on_startup 钩子
- deps.py:    AmritaCore 运行时装配（配置加载 -> set_config -> load_amrita）
"""

from .startup import onEnable

__all__ = ["onEnable"]
