import warnings

warnings.warn(
    "This module is deprecated and will be removed in a future version(1.2.0).Please import from `amrita_core` instead.",
    DeprecationWarning,
    stacklevel=2,
)
from amrita_sense.hook.exception import MatcherException as ChatException
from amrita_sense.hook.fun_typing import FunctionData
from amrita_sense.hook.matcher import (
    EventRegistry,
    Matcher,
    MatcherFactory,
)

__all__ = [
    "ChatException",
    "EventRegistry",
    "FunctionData",
    "Matcher",
    "MatcherFactory",
]
