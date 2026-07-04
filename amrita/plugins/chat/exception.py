import warnings

warnings.warn(
    "This module is deprecated and will be removed in a future version(1.2.0).Please import from `amrita_core` instead.",
    DeprecationWarning,
    stacklevel=2,
)
from amrita_core.hook.exception import (
    CancelException,
    MatcherException,
    PassException,
)

__all__ = [
    "CancelException",
    "MatcherException",
    "PassException",
]
