import asyncio

import nonebot
from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.adapters.onebot.v11.message import Message, MessageSegment
from nonebot.rule import Rule

from amrita.utils.bot_utils import init
from amrita.utils.plugins import load_plugins

init()
load_plugins()

from amrita.platform import ingress, shim
from amrita.plugins.chat.check_rule import is_bot_enabled, is_bot_globally_enabled


class FakeAdapter:
    def __init__(self):
        self.bots = {}
        self.driver = nonebot.get_driver()


class FakeBot(nonebot.adapters.Bot if hasattr(nonebot.adapters, "Bot") else object):
    def __init__(self):
        super().__init__(FakeAdapter(), "10000")

    async def call_api(self, api, **data):
        return {"message_id": 1, "role": "admin"}

    async def send(self, event, message, **kwargs):
        return None


async def main():
    await nonebot.get_driver()._lifespan.startup()

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=123,
        message_type="group",
        message_id=456,
        message=Message([MessageSegment.text("你好")]),
        raw_message="你好",
        font=0,
        sender={"user_id": 123, "nickname": "N"},
        to_me=True,
        group_id=789,
    )
    bot = FakeBot()

    # 1) 全生命周期下的入站转换（preprocessor 手动触发，与运行时同一实现）
    await ingress._bind_current_envelope(event, bot)
    env = shim.current_envelope()
    print(
        "[smoke] envelope:",
        env.kind,
        env.adapter,
        env.scope,
        env.actor.user_id,
        "role_known=",
        env.actor.role_known,
    )

    # 2) DI：rule 用 EnvelopeNBDep 声明参数，由 nonebot 解析
    from amrita.plugins.chat.config import config_manager

    print("[smoke] config.enable(原值) =", config_manager.config.enable)
    config_manager.config.enable = True

    ok = await Rule(is_bot_globally_enabled)(bot, event, {})
    print("[smoke] rule(is_bot_globally_enabled) ->", ok)

    ok2 = await Rule(is_bot_enabled)(bot, event, {})
    print("[smoke] rule(is_bot_enabled) ->", ok2)

    actor = await shim.role_of(env, bot)
    print("[smoke] role_of ->", actor.role, "role_known=", actor.role_known)

    # 3) 真实命令 handler：参数换成 EnvelopeNBDep 后仍能按 scope 取群号
    from nonebot_plugin_alconna import Match

    from amrita.plugins.manager import leave as leave_module

    class _Finished(Exception):
        pass

    async def _finish(message=""):
        raise _Finished(message)

    leave_module.set_leave.finish = staticmethod(_finish)

    class _LeaveBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.left = []

        async def get_group_member_info(self, **kwargs):
            return {"role": "member"}

        async def set_group_leave(self, group_id):
            self.left.append(group_id)

    leave_bot = _LeaveBot()
    try:
        await leave_module.leave(leave_bot, env, Match(result="--this", available=True))
    except _Finished as exc:
        print("[smoke] leave(--this) ->", exc, "| set_group_leave:", leave_bot.left)


asyncio.run(main())
print("[smoke] OK")
