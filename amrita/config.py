"""Amrita核心配置模块

该模块定义了Amrita机器人的核心配置模型和获取配置的方法。
"""

from typing import Literal

from nonebot import get_plugin_config, logger
from pydantic import BaseModel, model_validator


class AmritaConfig(BaseModel):
    """Amrita核心配置模型"""

    # 日志目录
    log_dir: str = "logs"

    max_event_record: int = 1000

    # 管理员群组ID
    admin_group: int = -1

    # 禁用的内置插件列表
    # disabled_builtin_plugins: list[Literal["chat", "manager", "perm", "menu", "webui"]] = [] # 注：Amrita不再允许禁用内置插件

    # Amrita日志级别
    amrita_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
        "WARNING"
    )

    # 公开群组ID（Bot对外展示）
    public_group: int = 0

    # 机器人名称
    bot_name: str = "Amrita"

    # 请求速率限制（间隔秒）
    rate_limit: int = 5

    # 是否禁用内置菜单
    disable_builtin_menu: bool = False

    # 是否自动通过好友申请
    auto_approve_friend_request: bool = True

    # 是否自动通过拉群申请
    auto_approve_group_request: bool = True

    usage_check_time: float = 400  # 添加usage的时间间隔(ms)

    # 是否禁用 /amrita 信息输出
    no_amrita_flag: bool = False

    @model_validator(mode="after")
    def _vali(self):
        if 10000 > self.admin_group > 0:
            logger.warning("Amrita config 'admin_group' is invalid, set to -1")
            self.admin_group = -1
        return self


def get_amrita_config() -> AmritaConfig:
    """获取Amrita配置

    Returns:
        AmritaConfig: Amrita配置对象
    """
    return get_plugin_config(AmritaConfig)
