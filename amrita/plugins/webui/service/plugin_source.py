"""插件商店：聚合 NoneBot 商店 registry 与 Amrita 官方插件清单。

两个来源：

- **NoneBot 商店** —— ``https://registry.nonebot.dev/plugins.json``，全量约 560 KB。
  由后端拉取并缓存，不让前端直连。
- **Amrita 官方插件** —— 随包分发的静态清单 ``official_plugins.json``。
  离线可用，不依赖网络。

两边都会被规范化成同一种 :class:`PluginSourceEntry`，前端只需处理一种结构。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from pathlib import Path
from typing import Any, Literal

import aiohttp
import nonebot
from packaging.requirements import Requirement

from amrita.utils.pyproject_io import PluginTarget

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TARGET",
    "NONEBOT_REGISTRY_URL",
    "OFFICIAL_PLUGINS_PATH",
    "PluginSourceEntry",
    "PluginSourceError",
    "PluginStore",
    "adapter_supported",
    "available_adapters",
    "get_plugin_store",
    "incompatible_reason",
]

NONEBOT_REGISTRY_URL = "https://registry.nonebot.dev/plugins.json"
OFFICIAL_PLUGINS_PATH = Path(__file__).resolve().parent / "official_plugins.json"

DEFAULT_TTL = 24 * 3600.0
DEFAULT_TIMEOUT = 10.0

#: 商店插件默认写入的配置段，与 ``ambot plugin add`` 保持一致。
DEFAULT_TARGET: PluginTarget = "amrita"

PluginSource = Literal["nonebot", "amrita"]


class PluginSourceError(RuntimeError):
    """插件源不可用或返回了非预期结构。"""


@dataclass
class PluginSourceEntry:
    """商店里的一条插件元信息。"""

    module_name: str
    name: str
    source: PluginSource
    target: PluginTarget = DEFAULT_TARGET
    project_link: str | None = None
    desc: str = ""
    author: str | None = None
    homepage: str | None = None
    tags: list[str] = field(default_factory=list)
    is_official: bool = False
    type: str = "application"
    supported_adapters: list[str] | None = None
    version: str | None = None
    valid: bool = True
    requires: dict[str, str] = field(default_factory=dict)
    """该插件对宿主环境的版本约束，形如 ``{"amrita": ">=1.10"}``。"""

    def to_dict(self) -> dict[str, Any]:
        """转成可直接 JSON 序列化的字典。"""
        return {
            "module_name": self.module_name,
            "name": self.name,
            "source": self.source,
            "target": self.target,
            "project_link": self.project_link,
            "desc": self.desc,
            "author": self.author,
            "homepage": self.homepage,
            "tags": list(self.tags),
            "is_official": self.is_official,
            "type": self.type,
            "supported_adapters": (
                list(self.supported_adapters)
                if self.supported_adapters is not None
                else None
            ),
            "version": self.version,
            "valid": self.valid,
            "requires": dict(self.requires),
        }


def _clean_tags(raw: Any) -> list[str]:
    """NoneBot registry 的 tags 是 ``[{"label": ..., "color": ...}]``。"""
    if not isinstance(raw, list):
        return []
    labels: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            label = item.get("label")
            if label:
                labels.append(str(label))
        elif isinstance(item, str):
            labels.append(item)
    return labels


def _parse_nonebot(raw: Mapping[str, Any]) -> PluginSourceEntry | None:
    """解析一条 NoneBot 商店条目，缺模块名则丢弃。"""
    module_name = str(raw.get("module_name") or "").strip()
    if not module_name:
        return None
    adapters = raw.get("supported_adapters")
    return PluginSourceEntry(
        module_name=module_name,
        name=str(raw.get("name") or module_name),
        source="nonebot",
        target=DEFAULT_TARGET,
        project_link=raw.get("project_link"),
        desc=str(raw.get("desc") or ""),
        author=raw.get("author"),
        homepage=raw.get("homepage"),
        tags=_clean_tags(raw.get("tags")),
        is_official=bool(raw.get("is_official")),
        type=str(raw.get("type") or "application"),
        supported_adapters=(
            [str(a) for a in adapters] if isinstance(adapters, list) else None
        ),
        version=raw.get("version"),
        valid=bool(raw.get("valid", True)),
    )


def _parse_official(raw: Mapping[str, Any]) -> PluginSourceEntry | None:
    """解析一条 Amrita 官方清单条目，缺模块名则丢弃。"""
    module_name = str(raw.get("module_name") or "").strip()
    if not module_name:
        return None
    target = raw.get("target")
    return PluginSourceEntry(
        module_name=module_name,
        name=str(raw.get("name") or module_name),
        source="amrita",
        target=target if target in ("amrita", "nonebot") else "amrita",
        project_link=raw.get("project_link") or module_name,
        desc=str(raw.get("desc") or ""),
        author=raw.get("author"),
        homepage=raw.get("homepage"),
        tags=[str(t) for t in raw.get("tags") or []],
        is_official=bool(raw.get("is_official", True)),
        type=str(raw.get("type") or "application"),
        supported_adapters=raw.get("supported_adapters"),
        version=raw.get("version"),
        valid=bool(raw.get("valid", True)),
        requires={str(k): str(v) for k, v in (raw.get("requires") or {}).items()},
    )


class PluginStore:
    """插件商店的拉取、缓存与检索。"""

    def __init__(
        self,
        *,
        url: str = NONEBOT_REGISTRY_URL,
        official_path: Path | str | None = None,
        ttl: float = DEFAULT_TTL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.url = url
        self.official_path = (
            Path(official_path) if official_path is not None else OFFICIAL_PLUGINS_PATH
        )
        self.ttl = ttl
        self.timeout = timeout

        self.warnings: list[str] = []
        """最近一次拉取过程中出现的问题，供接口层透出。"""

        self._cache: list[PluginSourceEntry] | None = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def stale(self) -> bool:
        """缓存是否已过期。从未拉取过时也视为过期。"""
        return self._cache is None or (time.monotonic() - self._fetched_at) > self.ttl

    def invalidate(self) -> None:
        """丢弃缓存，下次调用重新拉取。"""
        self._cache = None
        self._fetched_at = 0.0

    def _load_official(self) -> list[PluginSourceEntry]:
        """读取随包分发的官方插件清单。文件缺失或损坏时返回空列表。"""
        path = self.official_path
        if not path.is_file():
            self.warnings.append(f"官方插件清单不存在: {path}")
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.warnings.append(f"官方插件清单解析失败: {exc}")
            return []
        raw_items = payload.get("plugins") if isinstance(payload, Mapping) else payload
        if not isinstance(raw_items, list):
            self.warnings.append("官方插件清单结构非预期，已忽略")
            return []
        return [
            entry
            for entry in (
                _parse_official(item) for item in raw_items if isinstance(item, Mapping)
            )
            if entry is not None
        ]

    async def _fetch_nonebot(self) -> list[PluginSourceEntry]:
        """拉取 NoneBot 商店 registry。"""
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.url) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise PluginSourceError(f"拉取 NoneBot 插件商店失败: {exc}") from exc

        if not isinstance(payload, list):
            raise PluginSourceError("NoneBot 插件商店返回了非预期的结构")
        return [
            entry
            for entry in (
                _parse_nonebot(item) for item in payload if isinstance(item, Mapping)
            )
            if entry is not None
        ]

    async def entries(self, *, force: bool = False) -> list[PluginSourceEntry]:
        """返回合并后的商店清单。

        官方清单是本地文件，始终可用；NoneBot 商店拉取失败时退回上一次缓存，
        连缓存都没有就只返回官方部分，并在 :attr:`warnings` 里留痕。
        """
        async with self._lock:
            if not force and not self.stale:
                assert self._cache is not None
                return self._cache

            self.warnings = []
            official = self._load_official()
            try:
                remote = await self._fetch_nonebot()
            except PluginSourceError as exc:
                logger.warning("插件商店拉取失败：%s", exc)
                self.warnings.append(str(exc))
                if self._cache is not None:
                    return self._cache
                return official

            self._cache = [*official, *remote]
            self._fetched_at = time.monotonic()
            return self._cache

    async def search(
        self,
        *,
        query: str | None = None,
        sources: Iterable[PluginSource] | None = None,
        official: bool | None = None,
        tag: str | None = None,
        adapter: str | None = None,
        supported_only: bool = False,
        page: int = 1,
        size: int = 50,
        force: bool = False,
    ) -> tuple[list[PluginSourceEntry], int]:
        """按条件筛选并分页。

        Returns:
            ``(当前页条目, 命中总数)``。
        """
        items = await self.entries(force=force)
        wanted_sources = set(sources) if sources is not None else None
        needle = query.strip().lower() if query else None
        adapters = available_adapters() if supported_only else {}

        filtered: list[PluginSourceEntry] = []
        for item in items:
            if wanted_sources is not None and item.source not in wanted_sources:
                continue
            if official is not None and item.is_official is not official:
                continue
            if tag is not None and tag not in item.tags:
                continue
            if adapter is not None and not adapter_supported(
                item.supported_adapters, {"": adapter}
            ):
                continue
            if supported_only and not adapter_supported(
                item.supported_adapters, adapters
            ):
                continue
            if needle is not None and not (
                needle in item.module_name.lower()
                or needle in item.name.lower()
                or needle in item.desc.lower()
                or (item.author or "").lower().find(needle) >= 0
            ):
                continue
            filtered.append(item)

        total = len(filtered)
        safe_size = max(1, size)
        start = max(0, (max(1, page) - 1) * safe_size)
        return filtered[start : start + safe_size], total


def available_adapters() -> dict[str, str]:
    """当前运行时已注册的适配器：名称 -> 适配器类的模块路径。

    取自 nonebot 的适配器注册表而非 ``pyproject.toml``：配置里写什么不一定等于
    实际注册了什么。
    """
    adapters: dict[str, str] = {}
    for name, adapter_cls in nonebot.get_adapters().items():
        adapters[name] = getattr(adapter_cls, "__module__", "") or ""
    return adapters


def adapter_supported(
    supported: Iterable[str] | None, available: Mapping[str, str]
) -> bool:
    """该插件是否被当前可用的适配器支持。

    ``supported_adapters`` 为 ``None``（或空列表）表示没有适配器限制，属通用插件，
    一律算支持——商店里这类占多数，按「没写即不支持」处理会误伤一大片。

    比对用前缀匹配：registry 里写的是包路径（``nonebot.adapters.onebot.v11``），
    而适配器类的 ``__module__`` 通常是 ``<包>.adapter``。
    """
    if not supported:
        return True
    for item in supported:
        for module in available.values():
            if module and (module == item or module.startswith(f"{item}.")):
                return True
    return False


def incompatible_reason(requires: Mapping[str, str]) -> str | None:
    """检查版本约束与当前环境是否相容。

    Returns:
        相容返回 ``None``；否则返回一句人话，形如
        ``需要 amrita>=1.10，当前为 1.9.0``。
    """
    for name, spec in requires.items():
        try:
            installed = dist_version(name)
        except PackageNotFoundError:
            return f"需要 {name}{spec}，但环境中未安装 {name}"
        try:
            ok = Requirement(f"{name}{spec}").specifier.contains(
                installed, prereleases=True
            )
        except Exception:
            continue
        if not ok:
            return f"需要 {name}{spec}，当前为 {installed}"
    return None


_default_store: PluginStore | None = None


def get_plugin_store() -> PluginStore:
    """进程内共享的商店实例，缓存跨请求复用。"""
    global _default_store
    if _default_store is None:
        _default_store = PluginStore()
    return _default_store
