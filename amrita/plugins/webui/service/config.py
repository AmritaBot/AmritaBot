from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from nonebot import get_driver, get_plugin_config, logger
from nonebot_plugin_uniconf import BaseDataManager, UniConfigManager
from pydantic import BaseModel, Field

# 出厂默认密码（不安全）：检测到正在使用它时，WebUI 将拒绝所有访问
DEFAULT_WEBUI_PASSWORD = "admin123"


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


class WsConfig(BaseModel):
    """WebSocket 实时推送配置（/amrita/ui/ws 频道）"""

    system_interval: float = Field(default=2.0, description="system 频道推送间隔（秒）")
    bot_state_interval: float = Field(default=5.0, description="bot 状态检查间隔（秒）")
    log_pending_max: int = Field(
        default=5000, description="待广播日志队列上限（sink 线程写、dispatcher 消费）"
    )
    log_replay_limit: int = Field(
        default=500, description="订阅 logs 时默认回放的条数（tail 语义，非全量）"
    )
    log_replay_limit_max: int = Field(
        default=5000, description="前端可请求的回放条数上限（防呆）"
    )
    log_tail_chunk_size: int = Field(
        default=64 * 1024,
        description="从日志文件尾部读取时每次 seek 的块大小（字节）",
    )
    log_replay_batch: int = Field(
        default=20,
        description=(
            "日志回放每批发送条数（批间让出事件循环，实时日志可插队，"
            "避免回放历史时实时日志长时间滞后）"
        ),
    )
    allowed_origins: list[str] = Field(
        default_factory=list,
        description=(
            "WebSocket 额外允许的 Origin（同源请求自动放行，无需配置；"
            "用于反代等 Host 与 Origin hostname 不一致的部署，留空表示仅允许同站）"
        ),
    )
    auth_check_interval: float = Field(
        default=60.0,
        description=(
            "WS 连接内定期复检登录态的时间间隔（秒）：token 过期/登出后"
            "断开挂机连接，避免长连接长期有效"
        ),
    )


# 配置热重载钩子

WsConfigReloadHook = Callable[[WsConfig], Awaitable[None]]
_reload_hooks: list[WsConfigReloadHook] = []


def register_ws_config_reload_hook(hook: WsConfigReloadHook) -> None:
    """注册配置热重载钩子（幂等，重复注册自动去重）。"""
    if hook not in _reload_hooks:
        _reload_hooks.append(hook)


class DataManager(BaseDataManager[WsConfig]):
    """WebSocket 推送配置管理器（uniconf 持久化到 webui/config.toml，支持热重载）"""

    config: WsConfig
    config_class: type[WsConfig]
    _owner_name: str = "webui"
    __lateinit__ = True

    @classmethod
    def __init_classvars__(cls) -> None:
        """显式绑定配置类。

        本模块启用了 ``from __future__ import annotations``，注解是字符串；
        基类按注解推导 config_class 时只能用基类模块的命名空间解析，
        解析不到这里的 WsConfig。直接赋值绕开推导。
        """
        cls.config_class = WsConfig

    def _init(self) -> None:
        """覆写基类 _init：在 uniconf 的 on_reload 回调中追加热重载钩子。"""

        async def callback(owner_name: str, _path: Path) -> None:
            self.config = await UniConfigManager().get_config_by_class(
                self.config_class
            )
            logger.debug(f"{owner_name} config reloaded")
            for hook in _reload_hooks:
                try:
                    await hook(self.config)
                except Exception:  # noqa: PERF203
                    logger.exception(f"{owner_name} 配置重载钩子执行失败")

        async def init() -> None:
            await UniConfigManager().add_config(
                self.config_class,
                owner_name=self._owner_name,
                on_reload=callback,
            )
            await self.__apost_init__()

        if not self._inited:
            self._task = asyncio.create_task(init())
            self._inited = True


def is_using_default_password() -> bool:
    """是否仍在使用出厂默认密码（此时 WebUI 锁定，要求更换）。"""
    return get_webui_config().webui_password.strip() == DEFAULT_WEBUI_PASSWORD


@get_driver().on_startup
async def _() -> None:
    """启动时加载配置。"""
    await data_manager.safe_get_config()


data_manager = DataManager()
