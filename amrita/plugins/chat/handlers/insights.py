from collections.abc import Sequence

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot_plugin_amrita import CachedUserDataRepository
from nonebot_plugin_amrita.database import InsightsModel, UserDataExecutor, UserMetadata

from amrita.plugins.perm.API.rules import any_has_permission

from ..check_rule import is_bot_admin
from ..config import config_manager
from ..utils.sql import get_uni_user_id


async def insights(event: MessageEvent, matcher: Matcher, args: Message = CommandArg()):
    msg = "未知参数。"
    config = config_manager.config
    if not (arg := args.extract_plain_text().strip()):
        data = await CachedUserDataRepository().get_metadata(f"user_{event.user_id}")
        user_limit = config.usage_limit.user_daily_limit
        user_token_limit = config.usage_limit.user_daily_token_limit
        group_limit = config.usage_limit.group_daily_limit
        group_token_limit = config.usage_limit.group_daily_token_limit
        enable_limit = config.usage_limit.enable_usage_limit
        is_bypass = await is_bot_admin(event) or await (
            any_has_permission("amrita.usage.bypass")
        )(event)

        msg = (
            f"您今日的使用次数为：{data.called_count}/{user_limit if (user_limit != -1 and enable_limit and not is_bypass) else '♾'}次"
            + f"\n您今日的token使用量为：{data.tokens_input + data.tokens_output}/{user_token_limit if (user_token_limit != -1 and enable_limit and not is_bypass) else '♾'}tokens"
            + f"\n（输入：{data.tokens_input},输出：{data.tokens_output}）"
        )
        if isinstance(event, GroupMessageEvent):
            data = await CachedUserDataRepository().get_metadata(get_uni_user_id(event))
            msg = (
                f"群组使用次数为：{data.called_count}/{group_limit if (group_limit != -1 and enable_limit) else '♾'}次"
                + f"\n群组使用token为：{data.tokens_input + data.tokens_output}/{group_token_limit if (group_token_limit != -1 and enable_limit) else '♾'}tokens"
                + f"\n（输入：{data.tokens_input},输出：{data.tokens_output}）"
                + f"\n\n{msg}"
            )
    elif arg == "global":
        total_token_limit = config.usage_limit.total_daily_token_limit
        total_limit = config.usage_limit.total_daily_limit
        if not await is_bot_admin(event):
            await matcher.finish("你没有权限查看全局数据")
        data = await InsightsModel.get()
        msg = (
            f"\n今日全局数据：\n输入token使用量：{data.token_input}"
            + f"\n输出token使用量：{data.token_output}token"
            + f"\n总使用次数：{data.usage_count}/{total_limit}"
            + f"\n总使用token为：{data.token_input + data.token_output}/{total_token_limit}tokens"
            + "\n(您的限制：♾)"
        )
    elif arg.startswith("top10"):
        if not await is_bot_admin(event):
            await matcher.finish("你没有权限查看排名数据")

        # 获取top10数据
        top_users: Sequence[UserMetadata] = await UserDataExecutor.get_top_users(
            limit=20
        )

        if not top_users:
            msg = "暂无使用数据。"
        else:
            # 按group/private分类
            group_users: Sequence[UserMetadata] = []
            private_users: Sequence[UserMetadata] = []
            for user in top_users:
                if user.user_id.startswith("group_"):
                    group_users.append(user)
                else:
                    private_users.append(user)

            msg = "今日使用量Top10：\n"

            if group_users:
                msg += "\n📢 群组排名：\n"
                for i, user in enumerate(group_users[:10], 1):
                    user_id = (
                        user.user_id.split("_", 1)[1]
                        if "_" in user.user_id
                        else user.user_id
                    )
                    total_tokens = user.tokens_input + user.tokens_output
                    msg += f"{i}. 群{user_id}: {user.called_count}次, {total_tokens}tokens\n"

            if private_users:
                msg += "\n💬 私聊排名：\n"
                for i, user in enumerate(private_users[:10], 1):
                    user_id = (
                        user.user_id.split("_", 1)[1]
                        if "_" in user.user_id
                        else user.user_id
                    )
                    total_tokens = user.tokens_input + user.tokens_output
                    msg += f"{i}. 用户{user_id}: {user.called_count}次, {total_tokens}tokens\n"

    if isinstance(event, GroupMessageEvent):
        await matcher.finish(
            MessageSegment.at(event.user_id) + MessageSegment.text(f"\n{msg}")
        )
    # 私聊不支持 at 段（协议约束），仅发送文本
    await matcher.finish(MessageSegment.text(f"\n{msg}"))
