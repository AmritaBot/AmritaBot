"""
API.py
包含大部分常用的Amrita本体API接口
"""

from .utils.admin import send_forward_msg_to_admin, send_to_admin
from .utils.billing import (
    BillingProvider,
    check_quota,
    dispatch_usage,
    get_daily_usage,
    get_unit_usage,
    iter_unit_usage,
    register_billing_provider,
)
from .utils.bot_utils import init
from .utils.plugins import load_plugins
from .utils.rate import BucketRepoitory, TokenBucket, get_bucket
from .utils.send import send_forward_msg
from .utils.system_health import calculate_system_health, calculate_system_usage
from .utils.utils import get_amrita_version

__all__ = [
    "BillingProvider",
    "BucketRepoitory",
    "TokenBucket",
    "calculate_system_health",
    "calculate_system_usage",
    "check_quota",
    "dispatch_usage",
    "get_amrita_version",
    "get_bucket",
    "get_daily_usage",
    "get_unit_usage",
    "init",
    "iter_unit_usage",
    "load_plugins",
    "register_billing_provider",
    "send_forward_msg",
    "send_forward_msg_to_admin",
    "send_to_admin",
]
