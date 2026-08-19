import asyncio
import os
import sys
import traceback
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import nonebot
import nonebot.log
from amrita_sense import logging as amlog
from amrita_sense.logging import default_filter
from amrita_sense.logging import default_format as CUSTOM_FORMAT
from nonebot.log import default_format

from amrita.config import get_amrita_config
from amrita.utils.logging import LoggingData, LoggingEvent, normalize_log_level
from amrita.utils.utils import get_amrita_version

_loop_running: bool = False

if TYPE_CHECKING:
    # avoid sphinx autodoc resolve annotation failed
    # because loguru module do not have `Logger` class actually
    from loguru import Record


class EventRecorder:
    def write(self, message):
        record: Record = message.record
        exc = record.get("exception")
        formatted_tb: str | None = None
        exc_message = ""
        if exc:
            # loguru exception 是 (type, value, traceback) 三元组：
            # traceback/frame 不可序列化 -> 先格式化为字符串再存储
            exc_type, exc_value, exc_tb = exc
            exc_message = str(exc_value)
            formatted_tb = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            ).rstrip("\n")
        data = LoggingEvent(
            log_level=normalize_log_level(record["level"].name),
            description=record["message"],
            message=exc_message,
            traceback=formatted_tb,
        )
        logging_data = LoggingData._get_data_sync()
        logging_data.data.append(data)
        logging_data._save_sync()


def init():
    from nonebot import get_driver
    from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter
    from nonebot.adapters.onebot.v11 import Bot, MessageSegment

    from .admin import send_forward_msg_to_admin

    logger = nonebot.logger

    async def st():
        global _loop_running
        _loop_running = True

    class AsyncErrorHandler:
        def write(self, message):
            global _loop_running
            try:
                if _loop_running:
                    self.task = asyncio.create_task(self.process(message))

            except RuntimeError:
                print(
                    "RuntimeWarning:\nThis is a known bug.\nPlease ignore this warning.\n----------\n"
                )

        async def process(self, message):
            try:
                record: Record = message.record
                if record["level"].name == "ERROR":
                    # 处理异常 traceback
                    exc_info = record["exception"]
                    if exc_info:
                        traceback_str = "".join(
                            traceback.format_exception(
                                exc_info.type,
                                exc_info.value,
                                exc_info.traceback,
                            )
                        )
                    else:
                        traceback_str = "无堆栈信息"

                    content = (
                        f"错误信息: {record['message']}\n"
                        f"时间: {record['time']}\n"
                        f"模块: {record['name']}\n"
                        f"文件: {record['file'].path}\n"
                        f"行号: {record['line']}\n"
                        f"函数: {record['function']}\n"
                        f"堆栈信息:\n{traceback_str}"
                    )
                    try:
                        bot = nonebot.get_bot()
                    except Exception:
                        return
                    if isinstance(bot, Bot):
                        await send_forward_msg_to_admin(
                            bot,
                            "Amrita-Exception",
                            bot.self_id,
                            [MessageSegment.text(content)],
                        )

            except Exception as e:
                logger.warning(f"发送群消息失败: {e}")

    Path("plugins").mkdir(exist_ok=True)
    logger.remove(amlog.logger_id.value)
    new_id = logger.add(
        sys.stdout,
        level=0,
        diagnose=True,
        format=CUSTOM_FORMAT,
        filter=default_filter,
    )
    nonebot.log.logger_id = new_id
    amlog.logger = logger
    amlog.logger_id.value = new_id
    logger.add(AsyncErrorHandler(), level="ERROR")
    logger.add(EventRecorder(), level="WARNING")
    nonebot.init()
    get_driver().on_startup(st)
    logger.success(f"Amrita v{get_amrita_version()} is initializing......")
    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)
    config = get_amrita_config()
    log_dir = config.log_dir
    os.makedirs(log_dir, exist_ok=True)

    logger.add(
        f"{log_dir}/" + "{time}.log",  # 传入函数，每天自动更新日志路径
        level=config.amrita_log_level,
        format=default_format,
        rotation="00:00",
        retention=timedelta(days=7),
        encoding="utf-8",
        enqueue=True,
    )
