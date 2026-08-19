"""模型预设存储"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amrita_core import ModelPreset, PresetManager
from nonebot import logger
from nonebot_plugin_uniconf.manager import replace_env_vars


@dataclass
class LoadedPreset:
    preset: ModelPreset
    stem: str
    path: Path


class PresetStore:
    """模型预设的发现、校验与缓存"""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._loaded: list[LoadedPreset] = []
        self._by_name: dict[str, LoadedPreset] = {}

    def validate(self) -> None:
        """校验目录下所有预设文件"""
        for path in self.models_dir.glob("*.json"):
            try:
                model_data = ModelPreset.load(path)
                model_data.save(path)
                self._by_name[model_data.name] = LoadedPreset(
                    model_data, path.stem, path
                )
            except Exception as e:  # noqa: PERF203
                logger.opt(colors=True, raw=True).error(
                    f"Failed to validate preset '{path!s}' because '{e!s}'"
                )

    async def load_all(self, *, cache: bool = False) -> list[ModelPreset]:
        """加载全部预设并注册到 PresetManager"""
        if cache and self._loaded:
            return [lp.preset for lp in self._loaded]
        self._loaded.clear()
        self._by_name.clear()
        PresetManager()._presets.clear()
        for path in self.models_dir.glob("*.json"):
            model_data = ModelPreset.load(path).model_dump()
            preset_data = replace_env_vars(model_data)
            if not isinstance(preset_data, dict):
                raise TypeError("Expected replace_env_vars to return a dict")
            model_preset = ModelPreset.model_validate(preset_data)
            lp = LoadedPreset(model_preset, path.stem, path)
            self._by_name[model_preset.name] = lp
            self._loaded.append(lp)
            PresetManager().add_preset(model_preset)

        self._sync_default_preset()

        return [lp.preset for lp in self._loaded]

    def _sync_default_preset(self) -> None:
        """把配置选中的预设同步为 PresetManager 的默认预设。

        在此项目中，选中的预设只有一个：default 是且仅能是 config 已选中的
        预设（config.default_preset）。若未显式设置，PresetManager
        的 get_default_preset() 会随机挑选一个预设，导致运行时模型随机漂移
        （未预期行为）。每次加载预设后都重新指定，与配置保持一致。
        """
        from .config import config_manager

        PresetManager().set_default_preset(config_manager.config.default_preset)

    async def find(self, name: str, *, cache: bool = False) -> ModelPreset | None:
        """按名查找预设"""
        await self.load_all(cache=cache)
        lp = self._by_name.get(name)
        return lp.preset if lp else None

    def path_of(self, name: str) -> Path:
        """预设名对应的文件路径"""
        return self._by_name[name].path

    def forget(self, name: str) -> None:
        """移除预设名到路径的记录"""
        self._by_name.pop(name, None)

    def register_extra(self, key: str, default_value: Any) -> None:
        """给所有预设补默认 extra 字段并存盘"""
        for lp in self._loaded:
            lp.preset.extra.setdefault(key, default_value)
            lp.preset.save(lp.path)
