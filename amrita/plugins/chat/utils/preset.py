"""统一预设解析入口（阶段 4）。

消灭各调用点散落的 ``config_manager.get_preset(config.preset, cache=...)``
样板：默认取配置选中的预设，默认走缓存（``cache=True``）。
"""

from __future__ import annotations

from amrita_core import ModelPreset

from ..config import config_manager


async def resolve_preset(
    name: str | None = None, *, fix: bool = True, cache: bool = True
) -> ModelPreset:
    """解析预设名 -> ``ModelPreset``。

    Args:
        name: 预设名；``None`` 时取配置选中的预设（``config.preset``）
        fix: 找不到时回退（default -> 首个可用预设）并持久化选中。
            默认 ``True``：热路径自动修正失效的选中预设（如 default 被删除）
        cache: 是否走磁盘预设缓存（默认 ``True``，热路径友好）

    Returns:
        ``ModelPreset``：解析到的预设。``fix=True`` 时回退链保证非空
        （预设目录为空会自动创建 ``default``）。

    Raises:
        LookupError: ``fix=False`` 且目标预设不存在
    """
    if name is None:
        name = config_manager.config.preset
    preset = await config_manager.presets.get_preset(name, fix=fix, cache=cache)
    if preset is None:
        raise LookupError(f"预设 {name} 不存在")
    return preset


async def is_multimodal_enabled() -> bool:
    """当前运行是否真的能把图片交给模型。

    两个开关必须同时打开，缺一不可：

    - ``preset.config.multimodal``：本插件据此决定是否采集 / 落库图片；
    - ``config.llm.enable_multi_modal``（AmritaCore）：Core 据此决定是否在记忆
      限流时把图片内容剥成纯文本。

    只看其中一个就会出现错配：预设说支持而 Core 剥图（图片连同占位符一起消失），
    或预设说不支持而 Core 不剥图（base64 被送给纯文本模型，接口直接报错）。
    """
    if not config_manager.config.core.llm.enable_multi_modal:
        return False
    presets = [
        await resolve_preset(preset)
        for preset in [
            config_manager.config.preset,
            *config_manager.config.preset_extension.backup_preset_list,
        ]
    ]
    return any(p.config.multimodal for p in presets)
