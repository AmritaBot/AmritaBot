"""为了兼容，这里保留了import"""

import warnings

warnings.warn(
    "This module is deprecated and will be removed in a future version(1.2.0).Please import from `nonebot_plugin_uniconf` instead.",
    DeprecationWarning,
    stacklevel=2,
)

from nonebot_plugin_uniconf import (
    CALLBACK_TYPE,
    FILTER_TYPE,
    BaseDataManager,
    EnvfulConfigManager,
    UniConfigManager,
)

__all__ = [
    "CALLBACK_TYPE",
    "FILTER_TYPE",
    "BaseDataManager",
    "EnvfulConfigManager",
    "UniConfigManager",
]
