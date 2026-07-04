"""
API.py
包含大部分常用的Amrita本体API接口
"""

from .config_manager import BaseDataManager, UniConfigManager
from .utils.admin import send_forward_msg_to_admin, send_to_admin
from .utils.bot_utils import init
from .utils.plugins import load_plugins
from .utils.rate import BucketRepoitory, TokenBucket, get_bucket
from .utils.send import send_forward_msg
from .utils.system_health import calculate_system_health, calculate_system_usage
from .utils.utils import get_amrita_version

__all__ = [
    "BaseDataManager",
    "BucketRepoitory",
    "TokenBucket",
    "UniConfigManager",
    "calculate_system_health",
    "calculate_system_usage",
    "get_amrita_version",
    "get_bucket",
    "init",
    "load_plugins",
    "send_forward_msg",
    "send_forward_msg_to_admin",
    "send_to_admin",
]
