"""聊天插件匹配器管理模块

该模块负责管理聊天插件中的所有事件匹配器，包括消息、命令和通知事件的处理。
"""

from nonebot import MatcherGroup
from nonebot.rule import Rule

from ..menu.models import MatcherData
from .check_rule import (
    is_bot_admin,
    is_bot_enabled,
    is_group_admin,
    is_group_admin_if_is_in_group,
    should_respond_with_usage_check,
)
from .handlers.add_notices import add_notices
from .handlers.chat import entry as chat
from .handlers.chat_switch import chat as chat_switch
from .handlers.chatobj import chatobj_manage
from .handlers.debug_switchs import debug_switchs
from .handlers.insights import insights
from .handlers.mcp import mcp_command
from .handlers.model import model
from .handlers.poke_event import poke_event
from .handlers.prompt import prompt
from .handlers.recall import recall
from .handlers.session_cmd import session

# 创建基础匹配器组，所有匹配器都需满足is_bot_enabled规则
base_matcher = MatcherGroup(rule=is_bot_enabled)

# 添加通知事件处理器
base_matcher.on_notice(
    priority=5,
    block=False,
).append_handler(add_notices)

base_matcher.on_notice(
    priority=5,
    block=False,
).append_handler(poke_event)

base_matcher.on_notice(
    priority=5,
    block=False,
).append_handler(recall)

# 添加消息事件处理器，处理聊天消息
base_matcher.on_message(
    block=False,
    priority=11,
    rule=Rule(should_respond_with_usage_check, is_bot_enabled),
).append_handler(chat)

# 模型域
base_matcher.on_command(
    "model",
    aliases={"模型", "切换模型", "模型管理"},
    priority=10,
    block=True,
    permission=is_bot_admin,
    state=MatcherData(
        name="模型管理",
        description="查看、切换与测试模型",
        usage=(
            "/model — 查看当前模型；"
            "/model list — 可用模型；"
            "/model switch <名> — 切换；"
            "/model info — 当前详情；"
            "/model test [名] [-d] — 测试"
        ),
    ).model_dump(),
).append_handler(model)

# 提示词域
base_matcher.on_command(
    "prompt",
    priority=10,
    block=True,
    permission=is_group_admin_if_is_in_group,
    state=MatcherData(
        name="提示词管理",
        description="设置自定义提示词与切换模板",
        usage=(
            "/prompt — 查看；"
            "/prompt set <文本> — 设置；"
            "/prompt clear — 清空；"
            "/prompt template [group|private] [名称] — 模板"
        ),
    ).model_dump(),
).append_handler(prompt)

# 会话域
base_matcher.on_command(
    "session",
    aliases={"会话", "会话管理"},
    priority=10,
    block=True,
    force_whitespace=True,
    permission=is_group_admin_if_is_in_group,
    state=MatcherData(
        name="会话管理",
        description="会话信息、历史、压缩与记忆管理",
        usage=(
            "/session info — 元信息；"
            "/session list — 历史；"
            "/session use <编号> — 恢复；"
            "/session del <编号> — 删除；"
            "/session archive — 归档；"
            "/session clear — 清空；"
            "/session compact [force] — 压缩；"
            "/session forget — 清除记忆；"
            "/session abstract [clear] — 摘要"
        ),
    ).model_dump(),
).append_handler(session)

# 聊天开关域
base_matcher.on_command(
    "chat",
    aliases={"聊天开关", "chat_switch"},
    priority=10,
    block=True,
    permission=is_group_admin,
    state=MatcherData(
        name="聊天开关",
        description="开启/关闭聊天与自动回复",
        usage=(
            "/chat — 状态；"
            "/chat on|off — 聊天开关；"
            "/chat auto <on|off> — 自动回复；"
            "/chat status — 状态"
        ),
    ).model_dump(),
).append_handler(chat_switch)

# 调试
base_matcher.on_command(
    "debug",
    priority=10,
    block=True,
    permission=is_bot_admin,
    state=MatcherData(
        name="调试模式",
        description="调试模式开关（on/off/status）",
        usage="/debug <on|off|status>",
    ).model_dump(),
).append_handler(debug_switchs)

# 用量统计
base_matcher.on_command(
    "insights",
    aliases={"今日用量"},
    block=True,
    priority=10,
    state=MatcherData(
        name="用量统计",
        description="查看今日AI用量统计",
        usage="/insights [global|top10 <--group|private|all>]]",
    ).model_dump(),
).append_handler(insights)

# MCP 管理
base_matcher.on_command(
    "mcp",
    aliases={"MCP管理"},
    permission=is_bot_admin,
    state=MatcherData(
        name="mcp",
        description="管理MCP服务",
        usage="/mcp <stats [-d|--details];add <server_script>;del <server_script>;reload>",
    ).model_dump(),
).append_handler(mcp_command)

# 会话进程管理
base_matcher.on_command(
    "chatobj",
    aliases={"chat_obj"},
    permission=is_group_admin_if_is_in_group,
    state=MatcherData(
        name="chatobj",
        description="管理聊天对话",
        usage=(
            "/chatobj - 显示所有会话状态;"
            "/chatobj status - 显示所有会话状态;"
            "/chatobj terminate <ID前缀> - 终止指定会话;"
            "/chatobj kill <ID前缀> - 终止指定会话;"
            "/chatobj clear - 清除已完成的会话;"
        ),
    ).model_dump(),
).append_handler(chatobj_manage)
