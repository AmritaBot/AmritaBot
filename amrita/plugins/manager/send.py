"""主动推送消息命令：Alconna 解析目标与内容，出站经平台 Sender 发送。"""

from __future__ import annotations

from arclet.alconna import Alconna, Args, MultiVar
from nonebot.adapters import Bot
from nonebot_plugin_alconna import Match, on_alconna

from amrita.platform.di import EnvelopeNBDep
from amrita.platform.dto import GROUP, PRIVATE, Scope
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.utils.send import resolve_sender

group = on_alconna(
    Alconna("send_to.group", Args["target?", str], Args["content?", MultiVar(str)]),
    use_cmd_start=True,
    permission=is_lp_admin,
    default_state=MatcherData(
        name="推送群消息",
        description="用于向一个群发送消息",
        usage="/send_to.group [群号] [消息]",
        show_if="lp.admin",
    ).model_dump(),
)
user = on_alconna(
    Alconna("send_to.user", Args["target?", str], Args["content?", MultiVar(str)]),
    use_cmd_start=True,
    permission=is_lp_admin,
    default_state=MatcherData(
        name="推送私聊消息",
        description="用于向一个用户发送消息",
        usage="/send_to.user [用户ID] [消息]",
        show_if="lp.admin",
    ).model_dump(),
)


def _is_valid_target_id(raw: str) -> bool:
    """支持正整数及 Telegram 负数群组 ID（如 -100123456）。"""
    return raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit())


@group.handle()
async def _(
    bot: Bot,
    env: EnvelopeNBDep,
    target: Match[str],
    content: Match[tuple[str, ...]],
):
    target_id = target.result.strip() if target.available else ""
    message = " ".join(content.result).strip() if content.available else ""
    if not target_id or not message:
        await group.finish("❌ 请输入群号和消息")
    if not _is_valid_target_id(target_id):
        await group.finish("❌ 群号只能为数字发送失败。")
    scope = Scope(platform=env.scope.platform, kind=GROUP, id=target_id)
    sender = resolve_sender(bot, scope, adapter=env.adapter or None)
    if sender is None:
        await group.finish("❌ 当前平台不支持主动推送群消息。")
    try:
        await sender.send_text(message)
    except Exception as e:
        await group.finish(f"❌ {e}发送失败。")


@user.handle()
async def _(
    bot: Bot,
    env: EnvelopeNBDep,
    target: Match[str],
    content: Match[tuple[str, ...]],
):
    target_id = target.result.strip() if target.available else ""
    message = " ".join(content.result).strip() if content.available else ""
    if not target_id or not message:
        await user.finish("❌ 请输入用户ID和消息")
    if not _is_valid_target_id(target_id):
        await user.finish("❌ 用户ID只能为数字发送失败。")
    scope = Scope(platform=env.scope.platform, kind=PRIVATE, id=target_id)
    sender = resolve_sender(bot, scope, adapter=env.adapter or None)
    if sender is None:
        await user.finish("❌ 当前平台不支持主动推送私聊消息。")
    try:
        await sender.send_text(message)
    except Exception as e:
        await user.finish(f"❌ {e}发送失败。")
