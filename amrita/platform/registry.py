"""platform 到实现的注册表：按注册顺序探测事件与 Bot 归属。"""

from __future__ import annotations

from nonebot.adapters import Bot
from nonebot.log import logger
from pydantic import BaseModel

from .loader import load_ports
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
    load_ports()
    try:
        return _ports[name][0]
    except (KeyError, IndexError) as exc:
        raise LookupError(f"no platform port registered for {name!r}") from exc


def get_adapter(adapter: str) -> PlatformPort | None:
    """按具体实现名取端口（onebot11 / milky / telegram），未知返回 None。"""
    load_ports()
    return _by_adapter.get(adapter)


def all_for(name: str) -> list[PlatformPort]:
    load_ports()
    return list(_ports.get(name, ()))


def platforms() -> list[str]:
    load_ports()
    return list(_ports)


def resolve(raw_event: BaseModel, bot: Bot | None = None) -> PlatformPort | None:
    """按注册顺序探测事件属于哪个实现。

    只做形状/模块名判断，禁止在此处 import 具体适配器的类。
    """
    load_ports()
    for bucket in _ports.values():
        for port in bucket:
            if _safe_match(port, raw_event, bot):
                return port
    return None


def resolve_bot(bot: Bot) -> PlatformPort | None:
    """按注册顺序探测 Bot 属于哪个适配器实现。"""
    load_ports()
    for bucket in _ports.values():
        for port in bucket:
            matcher = getattr(port, "match_bot", None)
            if callable(matcher):
                try:
                    if matcher(bot):
                        return port
                except Exception:
                    continue
    return None


def _safe_match(port: PlatformPort, raw_event: BaseModel, bot: Bot | None) -> bool:
    """单个实现的探测失败不应影响后续实现。"""
    try:
        return port.match(raw_event, bot)
    except Exception:
        return False


def log_import_failure(error: BaseException) -> None:
    """平台实现导入失败只降级不致命，缺哪个平台从这里看。"""
    logger.opt(exception=error).warning(
        f"platform implementation import failed: {type(error).__name__}"
    )


def clear() -> None:
    """仅供测试使用。"""
    _ports.clear()
    _by_adapter.clear()
