import asyncio
import contextlib
from collections import defaultdict
from typing import Any, ClassVar
from weakref import WeakSet

import aiologic
from nonebot import get_driver, on_command, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    GroupBanNoticeEvent,
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.exception import IgnoredException
from nonebot.matcher import Matcher
from nonebot.message import run_preprocessor
from nonebot.params import CommandArg
from nonebot.rule import (
    CommandRule,
    EndswithRule,
    FullmatchRule,
    KeywordsRule,
    RegexRule,
    ShellCommandRule,
    StartswithRule,
    ToMeRule,
)
from pydantic import BaseModel
from typing_extensions import Self

from amrita import config, get_amrita_config
from amrita.cache import WeakValueLRUCache
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.admin import send_to_admin

from .models import add_usage
from .status_manager import StatusManager
from .utils import TokenBucket

watch_group = defaultdict(
    lambda: TokenBucket(rate=1 / get_amrita_config().rate_limit, capacity=1)
)
watch_user = defaultdict(
    lambda: TokenBucket(rate=1 / get_amrita_config().rate_limit, capacity=1)
)

_running_task: WeakSet[asyncio.Task] = WeakSet()

conf = config.get_amrita_config()


class UsageInsights:
    _record_lock: aiologic.Lock = aiologic.Lock()
    _record_tmp: ClassVar[list[tuple[str, int, int]]] = []
    _list_lock: aiologic.Lock = aiologic.Lock()

    @classmethod
    async def record_usage(cls, dt: tuple[str, int, int]):
        async with cls._list_lock:
            cls._record_tmp.append(dt)
        async with cls._record_lock:
            if not cls._record_tmp:
                return
            async with cls._list_lock:
                temp_list = list(cls._record_tmp)
                cls._record_tmp.clear()
            self_id = temp_list[0][0]
            msg_count = sum(item[1] for item in temp_list)
            api_count = sum(item[2] for item in temp_list)
            await add_usage(self_id, msg_count, api_count)
            await asyncio.sleep(max(conf.usage_check_time / 1000, 0))


class APICalledRepo:
    _repo: defaultdict[str, tuple[int, int]]  # (count, successful_count, cost)
    _lock_pool: WeakValueLRUCache[str, aiologic.Lock]
    _instance = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._repo = defaultdict(lambda: (0, 0))
            cls._lock_pool = WeakValueLRUCache[str, aiologic.Lock](
                capacity=1024, loose_mode=True
            )
        return cls._instance

    async def push(self, api: str, is_success: bool):
        async with self._lock(api):
            cache = self._repo[api]
            successful_times = cache[1] + (1 if is_success else 0)
            called_times = cache[0] + 1
            self._repo[api] = (called_times, successful_times)

    async def query(self, api: str) -> tuple[int, int]:
        return self._repo[api]

    async def query_all(self) -> dict[str, tuple[int, int]]:
        return dict(self._repo)

    async def remove(self, api: str):
        self._repo.pop(api, None)

    async def clear(self):
        self._repo.clear()

    def _lock(self, api: str):
        if (lock := self._lock_pool.get(api)) is None:
            lock = aiologic.Lock()
            self._lock_pool[api] = lock
        return lock


@on_notice(block=False, priority=10).handle()
async def _(event: GroupBanNoticeEvent):
    if event.user_id != event.self_id:
        return
    await send_to_admin(
        f"{get_amrita_config().bot_name}在群{event.group_id}中{f'被禁言了{event.duration / 60}分钟' if event.duration else '被解除了禁言'}，请不要错过这条消息。"
    )


@on_command(
    "set_enable",
    priority=2,
    state=MatcherData(
        name="Bot可用状态设置",
        usage="/set_enable <true/false>",
        description="设置Bot状态",
        show_if="lp.admin",
    ).model_dump(),
).handle()
async def _(event: MessageEvent, matcher: Matcher, args: Message = CommandArg()):
    if not await is_lp_admin(event):
        return
    arg = args.extract_plain_text().strip()
    if arg in ("true", "yes", "1", "on"):
        StatusManager().set_disable(False)
        StatusManager().set_unready(False)
        await matcher.finish("已启用")
    elif arg in ("false", "no", "0", "off"):
        StatusManager().set_disable(True)
        await matcher.finish("已关闭")
    else:
        await matcher.finish("请输入正确的参数，true/yes/1/on/false/no/0/off")


@on_message(priority=1, block=False).handle()
async def _(bot: Bot):
    async def _add():
        await UsageInsights.record_usage((str(bot.self_id), 1, 0))

    task = asyncio.create_task(_add())
    _running_task.add(task)
    task.add_done_callback(lambda t: _running_task.discard(t))


@run_preprocessor
async def run(matcher: Matcher, event: MessageEvent):
    if (not StatusManager().ready) and (not await is_lp_admin(event)):
        raise IgnoredException("Maintenance in progress, operation not supported.")
    has_text_rule = any(
        isinstance(
            checker.call,
            FullmatchRule
            | CommandRule
            | StartswithRule
            | EndswithRule
            | KeywordsRule
            | ShellCommandRule
            | RegexRule
            | ToMeRule,
        )
        for checker in matcher.rule.checkers
    )  # 检查该匹配器是否有文字类匹配类规则
    if not has_text_rule:
        return
    ins_id = str(
        event.group_id if isinstance(event, GroupMessageEvent) else event.user_id
    )
    data = watch_group if isinstance(event, GroupMessageEvent) else watch_user
    bucket = data[ins_id]
    if not bucket.consume() and (not await is_lp_admin(event)):
        raise IgnoredException("Rate limit exceeded, operation ignored.")


def make_api_call_hash(api: str, data: dict[str, Any]):
    return f"{id(data)!s}{api}"


@Bot.on_called_api  # 调整说明：将数据库操作调整为后处理来避免造成额外的CallAPI耗时。
async def _(
    bot: Bot, exception: Exception | None, api: str, data: dict[str, Any], result: Any
):
    async def _add():
        if "send" in api and "msg" in api:
            await UsageInsights.record_usage((str(bot.self_id), 0, 1))

    await APICalledRepo().push(api, exception is None)

    task = asyncio.create_task(_add())
    _running_task.add(task)
    task.add_done_callback(lambda t: _running_task.discard(t))


@get_driver().on_shutdown
def _():
    global _running_task
    if _running_task:
        tasks = list(_running_task)
        for task in tasks:
            with contextlib.suppress(Exception):
                task.cancel()
        _running_task.clear()


class Status(BaseModel):
    lables: list[str]
    data: list[int]
