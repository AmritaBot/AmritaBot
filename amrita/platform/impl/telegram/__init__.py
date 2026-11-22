"""Telegram 平台适配器注册：与 QQ 并列的独立 platform。"""

from __future__ import annotations

from ...registry import register
from .port import TelegramPort

register(TelegramPort())

__all__ = ["TelegramPort"]
