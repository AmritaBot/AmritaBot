from __future__ import annotations

from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    """
    Configuration for webui
    """

    webui_enable: bool = True
    webui_user_name: str = "admin"
    webui_password: str = "admin123"
    # 禁用 Dotenv 编辑（默认 true 防敏感数据泄露；为 true 时 WebUI 显示不可用，读写接口均拒绝）
    no_env_editor: bool = True


def get_webui_config() -> Config:
    return get_plugin_config(Config)


# 出厂默认密码（不安全）：检测到正在使用它时，WebUI 将拒绝所有访问
DEFAULT_WEBUI_PASSWORD = "admin123"


def is_using_default_password() -> bool:
    """是否仍在使用出厂默认密码（此时 WebUI 锁定，要求更换）。"""
    return get_webui_config().webui_password.strip() == DEFAULT_WEBUI_PASSWORD
