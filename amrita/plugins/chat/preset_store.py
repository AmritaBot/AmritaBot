"""模型预设存储"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amrita_core import ModelPreset
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
        # 默认创建：预设目录为空时创建一个 default 预设（初始状态）
        if not self._loaded:
            self.ensure_default_sync()

    async def load_all(self, *, cache: bool = False) -> list[ModelPreset]:
        """加载全部预设（不依赖全局 PresetManager 单例）"""
        if cache and self._loaded:
            return [lp.preset for lp in self._loaded]
        self._loaded.clear()
        self._by_name.clear()
        for path in self.models_dir.glob("*.json"):
            model_data = ModelPreset.load(path).model_dump()
            preset_data = replace_env_vars(model_data)
            if not isinstance(preset_data, dict):
                raise TypeError("Expected replace_env_vars to return a dict")
            model_preset = ModelPreset.model_validate(preset_data)
            lp = LoadedPreset(model_preset, path.stem, path)
            self._by_name[model_preset.name] = lp
            self._loaded.append(lp)

        # 默认创建：预设目录为空时创建一个 default 预设（初始状态）。
        # default 与其他预设无差别：可编辑、可删除，删除后不会自动复活。
        if not self._loaded:
            self.ensure_default_sync()

        return [lp.preset for lp in self._loaded]

    def ensure_default_sync(self) -> ModelPreset:
        """默认创建：确保存在名为 ``default`` 的预设；缺失时以 ``default.json`` 落地并登记。

        default 是普通预设，不做任何特殊处理；``default.json`` 已存在时直接
        加载（内容以文件为准）。供初始化/空目录场景调用。
        """
        existing = next(
            (lp for lp in self._loaded if lp.preset.name == "default"), None
        )
        if existing is not None:
            return existing.preset
        path = self.models_dir / "default.json"
        if path.exists():
            preset = ModelPreset.load(path)
        else:
            preset = ModelPreset(name="default")
            preset.save(path)
        lp = LoadedPreset(preset, path.stem, path)
        self._by_name["default"] = lp
        self._loaded.append(lp)
        return preset

    async def find(self, name: str, *, cache: bool = False) -> ModelPreset | None:
        """按名查找预设"""
        await self.load_all(cache=cache)
        lp = self._by_name.get(name)
        return lp.preset if lp else None

    def path_of(self, name: str) -> Path:
        """预设名对应的文件路径"""
        return self._by_name[name].path

    def forget(self, name: str) -> None:
        """移除预设名到路径的记录（缓存中的 _loaded 一并清理，保持一致性）"""
        self._by_name.pop(name, None)
        self._loaded = [lp for lp in self._loaded if lp.preset.name != name]

    def register_extra(self, key: str, default_value: Any) -> None:
        """给所有预设补默认 extra 字段并存盘"""
        for lp in self._loaded:
            lp.preset.extra.setdefault(key, default_value)
            lp.preset.save(lp.path)
