"""重构说明：
不再使用on_chat与on_poke区分，而是on_precompletion与on_completion通过函数签名的参数事件类型区分
"""

import warnings

from amrita_core.hook.on import on_completion, on_event, on_precompletion

warnings.warn(
    "This module is deprecated and will be removed in a future version(1.2.0).Please import from `amrita_core` instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["on_completion", "on_event", "on_precompletion"]
