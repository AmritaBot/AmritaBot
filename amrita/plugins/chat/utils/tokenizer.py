import warnings

warnings.warn(
    "This module is deprecated and will be removed in a future version(1.2.0).Please import from `amrita_core` instead.",
    DeprecationWarning,
    stacklevel=2,
)
from amrita_core.base.tokenizer import TokenizerManager as Tokenizer
from amrita_core.tokenizer import hybrid_token_count

__all__ = ["Tokenizer", "hybrid_token_count"]
