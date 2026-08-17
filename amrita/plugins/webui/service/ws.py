"""WebSocket 实时数据推送。

设计：
- 端点：/amrita/ui/ws（需登录，cookie 认证）
- 协议：客户端发送 JSON 命令，服务端按频道推送
  - 订阅：{"action":"subscribe","channels":["system","logs"]}
  - 退订：{"action":"unsubscribe","channels":["system"]}
  - 心跳：{"action":"ping"}
- 频道：
  - system: 系统资源（CPU/内存/磁盘/网络），按 WsConfig.system_interval 间隔推送，订阅即推快照
  - bot:    Bot 连接状态（变化时广播 + 订阅即推快照）
  - logs:   实时日志（劫持 loguru sink；仅本次 Bot 启动以来的日志，不混入 event.json 历史；订阅时按 tail 语义回放最新 N 条，N 由 WsConfig.log_replay_limit / 前端 opts 控制）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import weakref
from collections import deque
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import aiofiles
import nonebot
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from pytz import utc

from amrita.config import get_amrita_config
from amrita.utils.system_health import calculate_system_usage

from .authlib import TOKEN_KEY, TokenManager
from .config import WsConfig, data_manager, register_ws_config_reload_hook
from .main import app

logger = logging.getLogger(__name__)


# 级别 -> (icon_color, icon)，与 LoggingEvent.color/icon 保持一致
_LEVEL_META: dict[str, tuple[str, str]] = {
    "WARNING": ("yellow", "exclamation-triangle"),
    "ERROR": ("red", "bug"),
    "FATAL": ("purple", "times"),
    "INFO": ("green", "info"),
    "DEBUG": ("blue", "code"),
}


class ChannelHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = {}
        # 每个 WS 的发送锁：广播（dispatcher）与回放（订阅时）可能并发 send_json，
        # 不加锁会导致 FastAPI WebSocket 并发发送抛错 -> 连接异常断开 -> 无限重连循环
        self._locks: dict[WebSocket, asyncio.Lock] = {}

    def lock(self, ws: WebSocket) -> asyncio.Lock:
        if ws not in self._locks:
            self._locks[ws] = asyncio.Lock()
        return self._locks[ws]

    def subscribe(self, channel: str, ws: WebSocket) -> None:
        self._subscribers.setdefault(channel, set()).add(ws)

    def unsubscribe(self, channel: str, ws: WebSocket) -> None:
        if channel in self._subscribers:
            self._subscribers[channel].discard(ws)

    def remove_ws(self, ws: WebSocket) -> None:
        for subs in self._subscribers.values():
            subs.discard(ws)
        self._locks.pop(ws, None)

    def subscribers(self, channel: str) -> set[WebSocket]:
        return self._subscribers.get(channel, set())


hub = ChannelHub()


async def _send_json_locked(ws: WebSocket, message: dict) -> None:
    """同一 WS 的所有发送串行化——广播/回放/meta 并发 send 会断连。"""
    async with hub.lock(ws):
        await ws.send_json(message)


async def _send_to_subscriber(ws: WebSocket, message: dict) -> bool:
    """发送失败返回 False，由调用方剔除。"""
    try:
        await _send_json_locked(ws, message)
        return True
    except Exception:
        return False


async def _broadcast(channel: str, data: dict) -> None:
    """推送失败的订阅者静默剔除，不阻塞广播循环。"""
    message = {"channel": channel, "data": data}
    dead = [
        ws
        for ws in hub.subscribers(channel)
        if not await _send_to_subscriber(ws, message)
    ]
    for ws in dead:
        hub.remove_ws(ws)


def _system_payload() -> dict:
    usage = calculate_system_usage()
    return {
        "status": "online",  # 具体状态由 bot 频道负责
        "cpu_usage": usage.get("cpu_usage"),
        "memory_usage": usage.get("memory_usage"),
        "disk_usage": usage.get("disk_usage"),
        "network_io": usage.get("network_io"),
        "logical_cores": usage.get("logical_cores"),
    }


async def _system_loop() -> None:
    while True:
        try:
            await _broadcast("system", _system_payload())
        except Exception:
            logger.exception("system 频道推送失败")
        cfg = await data_manager.safe_get_config()
        await asyncio.sleep(cfg.system_interval)


async def _bot_loop() -> None:
    last_state: bool | None = None
    while True:
        try:
            from .main import try_get_bot

            connected = try_get_bot() is not None
            if connected != last_state:
                last_state = connected
                await _broadcast(
                    "bot", {"status": "online" if connected else "offline"}
                )
        except Exception:
            logger.exception("bot 频道推送失败")
        cfg = await data_manager.safe_get_config()
        await asyncio.sleep(cfg.bot_state_interval)


async def _log_dispatcher() -> None:
    """事件驱动日志分发：sink 写入后按入队顺序逐条广播，不轮询文件。

    _pending_logs 是待广播队列：sink（loguru 后台线程）append，
    dispatcher（事件循环线程）popleft 逐条广播，先到先发。
    不用「滑动窗口 + 游标」——窗口满后 len 不再增长，游标越过后
    while 条件恒假，实时推送会永久停止。
    完整日志持久化在 jsonl 文件（订阅回放用）。
    loop/Event 在此补齐（sink 在模块加载时安装，彼时无事件循环）。
    每次循环重新读取全局队列：配置热重载会整体重建队列（_rebuild_pending_logs）。
    """
    global _wake, _main_loop
    _main_loop = asyncio.get_running_loop()
    _wake = asyncio.Event()
    while True:
        await _wake.wait()
        _wake.clear()
        while True:
            pending = _pending_logs
            if pending is None:
                break
            try:
                item = pending.popleft()
            except IndexError:
                break
            await _broadcast("logs", item)


class _LogSink:
    """loguru sink：劫持实时日志。

    每条日志同时：
    1. 入待广播队列（dispatcher 消费后实时广播，先到先发）
    2. 追加到 jsonl 临时文件（本次启动完整日志，一行一个 JSON：time/level/payload）
    文件在每次 Bot 启动时删除重建（见 _init_log_file），不读不写 event.json。
    """

    def write(self, message: object) -> None:
        record = getattr(message, "record")
        level = record["level"].name
        color, icon = _LEVEL_META.get(level, ("blue", "code"))
        item = {
            "title": level,
            "desc": record["message"],
            "time": record["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "icon_color": color,
            "icon": icon,
        }
        # deque 的 append/popleft 是原子的：sink 线程写、dispatcher 线程读安全。
        # 队列在首次 WS 连接时才创建（见 _ensure_loops），之前产生的日志
        # 只落 jsonl 文件不排队——无人消费，广播无意义，回放可覆盖。
        if _pending_logs is not None:
            _pending_logs.append(item)
        # 持久化到文件（sink 在 loguru 后台线程执行，同步写即可）
        _append_log_file(level, record["message"], item["time"])
        # 线程安全唤醒事件循环
        if _main_loop is not None and _wake is not None:
            _main_loop.call_soon_threadsafe(_wake.set)


_pending_logs: deque[dict] | None = None
_wake: asyncio.Event | None = None
_main_loop: asyncio.AbstractEventLoop | None = None
_sink_id: int | None = None

# jsonl 临时文件持久化（本次启动完整日志，永不丢弃；每次启动删除重建）
# 懒加载：模块加载时只删除旧文件 + 计算路径（轻量）；
# 文件句柄在首次写入日志时才打开；回放读取在订阅 logs 时才进行。

_log_path: Path | None = None
_file_lock = threading.Lock()
_file_handle: TextIO | None = None


def _init_log_file() -> None:
    """启动初始化：删除上次启动的临时日志文件（只保留本次启动的日志）。

    懒加载设计：此处不做 open，文件句柄在首次 _append_log_file 时打开。
    """
    global _log_path
    log_dir = Path(get_amrita_config().log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = log_dir / "realtime.jsonl"
    # 启动即删除：只保留本次启动的日志
    _log_path.unlink(missing_ok=True)


def _append_log_file(level: str, payload: str, time_str: str) -> None:
    """追加一行 JSON（{time, level, payload}）。线程安全，失败静默。

    懒加载：首次调用时才 open 文件句柄（append 模式）。
    """
    global _file_handle
    try:
        with _file_lock:
            if _file_handle is None:
                if _log_path is None:
                    return
                _file_handle = open(_log_path, "a", encoding="utf-8")
            line = json.dumps(
                {"time": time_str, "level": level, "payload": payload},
                ensure_ascii=False,
            )
            _file_handle.write(line + "\n")
            _file_handle.flush()
    except Exception:
        pass


def _install_log_capture() -> None:
    """安装 loguru sink（幂等：重复调用先移除旧 sink，防热重载重复注册）。

    在模块加载时即调用：捕获本次 Bot 启动以来的全部日志（含启动早期），
    同时初始化 jsonl 文件（启动删除旧文件）。
    此时无需事件循环——sink 只写线程安全结构，广播由 dispatcher 补齐 loop 后驱动。
    """
    global _sink_id
    if _sink_id is not None:
        nonebot.logger.remove(_sink_id)
    _init_log_file()
    _sink_id = nonebot.logger.add(_LogSink(), level="INFO", enqueue=True)


# 模块加载即安装：保证「本次启动以来」的完整日志都在内存窗口 + jsonl 文件里
_install_log_capture()


async def _channel_snapshot(channel: str) -> dict | None:
    """订阅时立即推送的当前状态快照。

    bot/system 是事件驱动频道（状态变化才广播）：新订阅者若只等广播，
    会永远拿不到当前值（首次广播时订阅者往往还没上线）。

    返回 ``None`` 表示该频道没有快照，调用方应跳过推送——避免新增
    频道时因未实现快照而抛异常导致 WebSocket 连接被关闭。
    """
    if channel == "bot":
        from .main import try_get_bot

        connected = try_get_bot() is not None
        return {
            "channel": "bot",
            "data": {"status": "online" if connected else "offline"},
        }
    if channel == "system":
        return {"channel": "system", "data": _system_payload()}
    return None


async def _read_log_tail(limit: int) -> list[dict[str, Any]]:
    """从 jsonl 文件尾部读取最后 limit 条日志（tail -n limit 语义）。

    按块从文件末尾向前 seek，只解析所需的尾部行——长运行的 Bot
    日志文件可能很大，全量读取会浪费 IO 与内存。返回时间正序
    （文件顺序）的原始记录，最多 limit 条。文件不存在时返回空列表。
    """
    if _log_path is None:
        return []
    try:
        cfg = await data_manager.safe_get_config()
        chunk_size = cfg.log_tail_chunk_size
        async with aiofiles.open(_log_path, "rb") as f:
            await f.seek(0, os.SEEK_END)
            pos = await f.tell()
            buf = b""
            lines: list[str] = []
            while pos > 0 and len(lines) < limit:
                read_size = min(chunk_size, pos)
                pos -= read_size
                await f.seek(pos)
                buf = (await f.read(read_size)) + buf
                lines = buf.decode("utf-8", errors="ignore").splitlines()
        items: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items[-limit:]
    except Exception:
        return []


async def _send_log_replay(ws: WebSocket, limit: int | None = None) -> None:
    """订阅 logs 时回放本次启动以来**最后 limit 条**日志（tail 语义）。

    不全量回放：长运行的 Bot 可能产生数万条日志，全量回放会一次性
    压垮前端（UI 卡死）。只发送文件尾部最新 limit 条，按时间正序发送。
    limit 为 None 时使用配置 log_replay_limit。
    """
    if limit is None:
        cfg = await data_manager.safe_get_config()
        limit = cfg.log_replay_limit
    for item in await _read_log_tail(limit):
        level = item.get("level", "INFO")
        color, icon = _LEVEL_META.get(level, ("blue", "code"))
        # 持锁发送：与 dispatcher 广播串行，避免并发 send 导致连接异常
        await _send_json_locked(
            ws,
            {
                "channel": "logs",
                "data": {
                    "title": level,
                    "desc": item.get("payload", ""),
                    "time": item.get("time", ""),
                    "icon_color": color,
                    "icon": icon,
                },
            },
        )


_started = False

_background_tasks: weakref.WeakSet[asyncio.Task] = weakref.WeakSet()


def _spawn_background(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """登记到 WeakSet：driver shutdown 统一取消，任务结束自动移除。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    return task


@nonebot.get_driver().on_shutdown
async def _cancel_background_tasks() -> None:
    """driver shutdown 时取消，避免事件循环关闭残留 pending task。"""
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _ensure_loops() -> None:
    global _started, _pending_logs
    if _started:
        return
    # 待广播队列依赖配置（maxlen），只能在事件循环里异步初始化；
    # 首次 WS 连接前 sink 产生的日志已全部落 jsonl，回放可覆盖，不丢失。
    # 初始化失败不置 _started，下次连接可重试。
    if _pending_logs is None:
        cfg = await data_manager.safe_get_config()
        _pending_logs = deque(maxlen=cfg.log_pending_max)
    _started = True
    # 注意：不再调用 _install_log_capture() —— sink 在模块加载时已安装，
    # 重复安装会重建 jsonl 文件（unlink 旧文件），导致「本次启动」日志丢失
    _spawn_background(_system_loop())
    _spawn_background(_bot_loop())
    _spawn_background(_log_dispatcher())


def _rebuild_pending_logs(cfg: WsConfig) -> None:
    """配置热重载后按新的 log_pending_max 重建待广播队列。

    保留旧队列中尚未广播的日志（超出新上限的丢弃最旧，tail 语义）。
    在事件循环内执行：dispatcher 每次循环重新读取全局队列，无需担心
    引用悬挂；sink 线程在重建瞬间并发写入的少量日志仍会落 jsonl
    文件（回放可覆盖），不丢失。
    """
    global _pending_logs
    new_queue: deque[dict] = deque(maxlen=cfg.log_pending_max)
    if _pending_logs is not None:
        new_queue.extend(_pending_logs)
    _pending_logs = new_queue


async def _on_ws_config_reloaded(cfg: WsConfig) -> None:
    """webui/config.toml 热重载钩子：按新参数重建待广播队列。"""
    _rebuild_pending_logs(cfg)


# 注册重载钩子：修改配置文件后自动按新 log_pending_max 重建队列
register_ws_config_reload_hook(_on_ws_config_reloaded)


@app.websocket("/amrita/ui/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 端点：先认证，再按订阅推送。"""
    await ws.accept()

    # Cookie 认证（WebSocket 无法重定向，直接关闭）
    token = ws.cookies.get(TOKEN_KEY)
    token_manager = TokenManager()
    if not token:
        await ws.close(code=4401, reason="未授权")
        return
    token_data = await token_manager.get_token_data(token, None)
    if token_data is None or token_data.expire < datetime.now(utc):
        await ws.close(code=4401, reason="未授权")
        return

    await _ensure_loops()

    channels: set[str] = set()
    try:
        while True:
            raw = await ws.receive_json()
            action = raw.get("action")
            if action == "subscribe":
                # 前端可控制日志回放条数：{"action":"subscribe","channels":["logs"],"opts":{"logs":{"limit":N}}}
                cfg = await data_manager.safe_get_config()
                opts = raw.get("opts") or {}
                logs_opts = opts.get("logs") or {}
                try:
                    logs_limit = int(
                        logs_opts.get("limit", cfg.log_replay_limit)
                    )
                except (TypeError, ValueError):
                    logs_limit = cfg.log_replay_limit
                logs_limit = min(max(logs_limit, 1), cfg.log_replay_limit_max)
                for ch in raw.get("channels", []):
                    if ch in ("system", "bot", "logs"):
                        if ch == "logs" and ch not in channels:
                            # 首次订阅 logs：回放本次启动以来最后 logs_limit 条
                            await _send_log_replay(ws, logs_limit)
                        elif ch not in channels:
                            # 首次订阅 bot/system：立即推当前状态快照，
                            # 避免新订阅者要等下一次变化才能拿到数据；
                            # 无快照的频道跳过推送
                            snapshot = await _channel_snapshot(ch)
                            if snapshot is not None:
                                await _send_json_locked(ws, snapshot)
                        hub.subscribe(ch, ws)
                        channels.add(ch)
                await ws.send_json(
                    {"channel": "meta", "data": {"subscribed": sorted(channels)}}
                )
            elif action == "unsubscribe":
                for ch in raw.get("channels", []):
                    hub.unsubscribe(ch, ws)
                    channels.discard(ch)
                await ws.send_json(
                    {"channel": "meta", "data": {"subscribed": sorted(channels)}}
                )
            elif action == "ping":
                await ws.send_json({"channel": "meta", "data": {"pong": True}})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove_ws(ws)
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
