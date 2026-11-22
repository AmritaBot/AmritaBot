"""实现发现：用 core 的副作用导入扫描 impl 命名空间，失败只降级不致命。"""

from __future__ import annotations

from importlib import import_module

from amrita_core.utils import side_effect_import
from nonebot.log import logger

IMPL_PACKAGE = f"{__package__}.impl"

_loaded = False


def load_ports() -> None:
    """扫描 impl 命名空间并副作用导入，命名空间里有什么平台就注册什么。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        namespace = import_module(IMPL_PACKAGE)
    except ImportError:
        logger.warning(f"platform implementation namespace missing: {IMPL_PACKAGE}")
        return
    for item in side_effect_import(namespace, False):
        if isinstance(item, BaseException):
            # 单个平台装坏不该让整个框架起不来，缺哪个看 registry 的空列表
            logger.opt(exception=item).warning("platform implementation import failed")


__all__ = ["IMPL_PACKAGE", "load_ports"]
