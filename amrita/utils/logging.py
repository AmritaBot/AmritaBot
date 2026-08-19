from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, cast

import aiofiles
from aiologic import Lock
from pydantic import BaseModel, Field

from amrita.config import get_amrita_config

_lock = Lock()

# loguru 默认级别（TRACE/DEBUG/INFO/SUCCESS/WARNING/ERROR/CRITICAL）
# + FATAL（历史 event.json 兼容）。
LogLevel = Literal[
    "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL", "FATAL"
]

_LOG_LEVEL_NAMES = frozenset(LogLevel.__args__)


def normalize_log_level(name: str) -> LogLevel:
    """将任意字符串级别名收敛到 LogLevel 值域。

    loguru 允许自定义级别名，EventRecorder sink 可能收到任意名字；
    未知级别一律降级为 WARNING，避免 pydantic 校验失败导致事件丢失。
    """
    if name in _LOG_LEVEL_NAMES:
        return cast(LogLevel, name)
    return "WARNING"


class LoggingEvent(BaseModel):
    log_level: LogLevel
    description: str
    message: str
    # 格式化后的完整堆栈（traceback.format_exception 产物，纯字符串，可 JSON 序列化）。
    # traceback/frame 对象本身不可序列化，因此写入 event.json 前必须格式化。
    traceback: str | None = None
    time: datetime = Field(default_factory=datetime.now)

    @property
    def color(self):
        match self.log_level:
            case "WARNING":
                return "yellow"
            case "ERROR":
                return "red"
            case "CRITICAL":
                return "darkred"
            case "FATAL":
                return "purple"
            case "INFO":
                return "green"
            case "DEBUG":
                return "blue"
            case "TRACE":
                return "gray"
            case "SUCCESS":
                return "teal"

    @property
    def icon(self):
        match self.log_level:
            case "WARNING":
                return "exclamation-triangle"
            case "ERROR":
                return "bug"
            case "CRITICAL":
                return "skull"
            case "FATAL":
                return "times"
            case "INFO":
                return "info"
            case "DEBUG":
                return "code"
            case "TRACE":
                return "code"
            case "SUCCESS":
                return "check"


class LoggingData(BaseModel):
    data: list[LoggingEvent] = []

    @staticmethod
    def _limit_length(data: LoggingData):
        while len(data.data) > get_amrita_config().max_event_record:
            data.data.pop(0)

    def _save_sync(self):
        self._limit_length(self)
        log_path = Path(get_amrita_config().log_dir) / "event.json"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json())

    async def save(self):
        self._limit_length(self)
        async with _lock:
            async with aiofiles.open(
                Path(get_amrita_config().log_dir) / "event.json", "w", encoding="utf-8"
            ) as f:
                await f.write(self.model_dump_json())

    @staticmethod
    async def get():
        log_path = Path(get_amrita_config().log_dir) / "event.json"
        if not log_path.exists():
            data = LoggingData()
            async with aiofiles.open(log_path, "w", encoding="utf-8") as f:
                await f.write(data.model_dump_json())
        else:
            async with aiofiles.open(log_path, encoding="utf-8") as f:
                data = LoggingData.model_validate_json(await f.read())
        return data

    @staticmethod
    def _get_data_sync():
        log_path = Path(get_amrita_config().log_dir) / "event.json"
        if not log_path.exists():
            data = LoggingData()
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(data.model_dump_json())
        else:
            with open(log_path, encoding="utf-8") as f:
                data = LoggingData.model_validate_json(f.read())
        return data

    async def append(self, event: LoggingEvent):
        self.data.append(event)
        await self.save()
