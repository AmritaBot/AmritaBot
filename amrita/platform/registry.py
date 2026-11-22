"""platform → 实现的注册表。

匹配顺序即注册顺序；QQ 平台下 onebot 与 milky 同时注册，先注册者先匹配，
因此 ``onebot.py`` 的 ``match`` 必须足够严格（只看 onebot 特征），
而 ``milky.py`` 可以宽松一些。
"""

from __future__ import annotations

from nonebot.adapters import Bot
from pydantic import BaseModel

from .ports import PlatformPort

_ports: dict[str, list[PlatformPort]] = {}
_by_adapter: dict[str, PlatformPort] = {}


def register(port: PlatformPort) -> None:
    """按 platform 名注册一个适配器实现，重复注册幂等（以类名为键）。"""
    bucket = _ports.setdefault(port.name, [])
    if any(type(existing) is type(port) for existing in bucket):
        return
    bucket.append(port)
    _by_adapter[port.adapter] = port


def get(name: str) -> PlatformPort:
    """取某平台的首个实现，没有则抛 LookupError。"""
    try:
        return _ports[name][0]
    except (KeyError, IndexError) as exc:
        raise LookupError(f"no platform port registered for {name!r}") from exc


def get_adapter(adapter: str) -> PlatformPort | None:
    """按具体实现名取端口（onebot11 / milky），未知返回 None。"""
    return _by_adapter.get(adapter)


def all_for(name: str) -> list[PlatformPort]:
    return list(_ports.get(name, ()))


def platforms() -> list[str]:
    return list(_ports)


def resolve(raw_event: BaseModel, bot: Bot | None = None) -> PlatformPort | None:
    """按注册顺序探测事件属于哪个实现。

    只做形状/模块名判断，禁止在此处 import 具体适配器的类。
    """
    for bucket in _ports.values():
        for port in bucket:
            if _safe_match(port, raw_event, bot):
                return port
    return None


def _safe_match(port: PlatformPort, raw_event: BaseModel, bot: Bot | None) -> bool:
    """单个实现的探测失败不应影响后续实现。"""
    try:
        return port.match(raw_event, bot)
    except Exception:
        return False


def clear() -> None:
    """仅供测试使用。"""
    _ports.clear()
    _by_adapter.clear()
