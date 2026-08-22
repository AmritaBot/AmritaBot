"""预设解析领域服务。

负责"配置选中预设 + 磁盘预设"的解析、回退与校验语义，与磁盘访问
（``PresetStore``）解耦。热路径默认走缓存（``cache=True``），
热重载等需要强制刷新的场景显式传 ``cache=False``。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from amrita_core import ModelPreset

from ..preset_store import PresetStore

if TYPE_CHECKING:
    from ..config import Config


class PresetService:
    """预设领域服务（由 ConfigManager 组合注入）"""

    def __init__(
        self,
        store: PresetStore,
        get_ins_config: Callable[[], Config],
        save_config: Callable[[], Awaitable[None]],
    ) -> None:
        self._store = store
        self._get_ins_config = get_ins_config
        self._save_config = save_config

    @property
    def _ins_config(self) -> Config:
        """实际配置实例（fix 写回用）"""
        return self._get_ins_config()

    def validate(self) -> None:
        """校验目录下所有预设文件"""
        self._store.validate()

    async def get_all_presets(self, *, cache: bool = True) -> list[ModelPreset]:
        """获取全部预设（默认走缓存）。

        预设全部来自磁盘目录（``models/*.json``）；``default`` 与普通预设
        无差别，仅当目录为空时由 ``PresetStore`` 默认创建一个。

        Args:
            cache: 是否使用磁盘预设缓存；热重载时显式传 ``False`` 强制刷新
        """
        return await self._store.load_all(cache=cache)

    async def get_preset(
        self, preset: str, fix: bool = False, *, cache: bool = True
    ) -> ModelPreset | None:
        """解析预设名 → ``ModelPreset``。

        - 磁盘预设按名查找（默认缓存），default 无任何特殊处理
        - ``fix=True`` 且找不到时回退到 ``default``（亦不存在则回退到
          第一个可用预设），并持久化写回选中预设；预设目录为空时
          ``load_all`` 会默认创建 ``default``，因此回退始终有结果

        Args:
            preset: 预设名称
            fix: 找不到时是否回退并保存配置
            cache: 是否使用磁盘预设缓存（默认 True）
        """
        if (model := await self._store.find(preset, cache=cache)) is not None:
            return model
        if fix:
            fallback = await self._store.find("default", cache=cache)
            if fallback is None:
                presets = await self._store.load_all(cache=cache)
                fallback = presets[0] if presets else None
            if fallback is not None:
                self._ins_config.preset = fallback.name
                await self._save_config()
                return fallback
        return None

    def get_preset_path(self, name: str) -> Path:
        """预设名对应的文件路径"""
        return self._store.path_of(name)

    def forget_preset(self, name: str) -> None:
        """移除预设名到路径的记录"""
        self._store.forget(name)
