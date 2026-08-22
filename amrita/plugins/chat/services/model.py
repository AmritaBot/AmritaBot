"""模型配置领域服务。

负责模型相关配置项的注册与预设 extra 字段的维护，
供 WebUI / 模型管理命令复用。
"""

from __future__ import annotations

from typing import Any

from ..preset_store import PresetStore


class ModelConfigService:
    """模型配置领域服务（由 ConfigManager 组合注入）"""

    def __init__(
        self,
        preset_store: PresetStore,
    ) -> None:
        self._preset_store = preset_store

    def reg_model_config(self, key: str, default_value: Any = None) -> None:
        """注册模型配置项：写入 default 预设的 extra，并为全部已加载预设补默认值。

        Args:
            key: 配置项名称
            default_value: 默认值（None 时以字符串 ``"null"`` 落盘）
        """
        if default_value is None:
            default_value = "null"
        # default 预设以磁盘 default.json 承载（配置不再内嵌），
        # 先同步兜底确保其存在，再给所有已加载预设补默认值并存盘
        self._preset_store.ensure_default_sync()
        self._preset_store.register_extra(key, default_value)
