from amrita_core import UniResponseUsage, call_completion
from amrita_core.libchat import (
    _call_with_reflection,
    _validate_msg_list,
    get_last_response,
    get_tokens,
    text_generator,
    tools_caller,
)
from nonebot.adapters.onebot.v11 import Event

from amrita.plugins.chat.config import config_manager
from amrita.plugins.chat.utils.app import CachedUserDataRepository, UserMetadataSchema
from amrita.plugins.chat.utils.sql import InsightsModel
from amrita.plugins.perm.API.rules import any_has_permission

is_bot_admin = None


def add_usage(
    ins: InsightsModel | UserMetadataSchema, usage: UniResponseUsage[int] | None
) -> None:
    """累加 token 用量"""
    if isinstance(ins, InsightsModel):
        if usage:
            ins.token_output += usage.completion_tokens
            ins.token_input += usage.prompt_tokens
        ins.usage_count += 1
    else:
        if usage:
            ins.tokens_input += usage.prompt_tokens
            ins.tokens_output += usage.completion_tokens
            ins.total_input_token += usage.prompt_tokens
            ins.total_output_token += usage.completion_tokens
        ins.called_count += 1
        ins.total_called_count += 1


async def usage_enough(event: Event) -> bool:
    global is_bot_admin
    if is_bot_admin is None:
        from ..check_rule import is_bot_admin

        is_bot_admin = is_bot_admin
    dm = CachedUserDataRepository()

    config = config_manager.config
    if not config.usage_limit.enable_usage_limit:
        return True
    elif await is_bot_admin(event):
        return True
    elif await (any_has_permission("amrita.usage.bypass"))(event):
        return True

    # ### Starts of Global Insights ###
    global_insights = await InsightsModel.get()
    if (
        config.usage_limit.total_daily_limit != -1
        and global_insights.usage_count >= config.usage_limit.total_daily_limit
    ):
        return False

    if config.usage_limit.total_daily_token_limit != -1 and (
        global_insights.token_input + global_insights.token_output
        >= config.usage_limit.total_daily_token_limit
    ):
        return False

    # ### End of global insights ###

    # ### User insights ###
    user_id = int(event.get_user_id())
    data: UserMetadataSchema = await dm.get_metadata(user_id, False)
    if (
        data.called_count >= config.usage_limit.user_daily_limit
        and config.usage_limit.user_daily_limit != -1
    ):
        return False
    if (
        config.usage_limit.user_daily_token_limit != -1
        and (data.tokens_input + data.tokens_output)
        >= config.usage_limit.user_daily_token_limit
    ):
        return False

    # ### End of user check ###

    # ### Start of group check ###
    group_id: int | None
    if (group_id := getattr(event, "group_id", None)) is not None:
        data = await dm.get_metadata(group_id, True)

        if (
            config.usage_limit.group_daily_limit != -1
            and data.called_count >= config.usage_limit.group_daily_limit
        ):
            return False
        if (
            config.usage_limit.group_daily_token_limit != -1
            and data.tokens_input + data.tokens_output
            >= config.usage_limit.group_daily_token_limit
        ):
            return False

    # ### End of group check ###

    return True


__all__ = [
    "_call_with_reflection",
    "_validate_msg_list",
    "add_usage",
    "call_completion",
    "get_last_response",
    "get_tokens",
    "text_generator",
    "tools_caller",
]
