"""实现发现：扫描 impl 命名空间，导入即注册，缺哪个平台都不致命。"""

from __future__ import annotations

import pkgutil
from importlib import import_module

from nonebot.log import logger

IMPL_PACKAGE = f"{__package__}.impl"

_loaded = False


def load_ports() -> None:
    """导入 impl 下所有实现包；impl 是不带 __init__ 的命名空间包，外部发行版可各自往里放平台。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        namespace = import_module(IMPL_PACKAGE)
    except ImportError:
        logger.warning(f"platform implementation namespace missing: {IMPL_PACKAGE}")
        return
    for module in pkgutil.iter_modules(list(getattr(namespace, "__path__", ()))):
        if not module.ispkg:
            continue  # 只有包才算一个平台实现，散落的单文件模块不参与注册
        name = f"{IMPL_PACKAGE}.{module.name}"
        try:
            import_module(name)
        except Exception as exc:  # 单个平台装坏不该让整个框架起不来
            logger.opt(exception=exc).warning(
                f"platform implementation import failed: {name}"
            )


__all__ = ["IMPL_PACKAGE", "load_ports"]
