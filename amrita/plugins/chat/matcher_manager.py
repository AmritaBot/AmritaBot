"""聊天插件匹配器管理模块

该模块负责管理聊天插件中的所有事件匹配器，包括消息、命令和通知事件的处理。

所有匹配器以数据驱动方式声明在 MATCHERS 路由表中，
由 _register 统一按规格注册，避免重复的注册样板代码。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from nonebot import MatcherGroup
from nonebot.rule import Rule

from ..menu.models import MatcherData
from .check_rule import (
    is_bot_admin,
    is_bot_enabled,
    is_bot_globally_enabled,
    is_group_admin,
    is_group_admin_if_is_in_group,
    should_respond_with_usage_check,
)
from .handlers import (
    add_notices,
    chat,
    chat_switch,
    chatobj_manage,
    debug_switchs,
    insights,
    mcp_command,
    model,
    poke_event,
    prompt,
    recall,
    session,
)

# 创建基础匹配器组，所有匹配器都需满足is_bot_enabled规则
base_matcher = MatcherGroup(rule=is_bot_enabled)

# 聊天开关匹配器组：仅检查全局开关，不受每群 enable 标记影响，
# 避免 /chat off 关闭群聊后无法再次执行 /chat on
chat_switch_matcher = MatcherGroup(rule=is_bot_globally_enabled)


@dataclass(frozen=True)
class MatcherSpec:
    """匹配器注册规格（数据驱动路由表条目）

    字段均为 None / False 时不传入 NoneBot，使用框架默认值。
    """

    handler: Callable[..., Any]
    kind: Literal["command", "message", "notice"] = "command"
    group: MatcherGroup | None = None
    # command 专用
    command: str | None = None
    aliases: set[str] | None = None
    force_whitespace: bool | None = None
    # 通用
    priority: int | None = None
    block: bool | None = None
    permission: Any | None = None
    rule: Rule | None = None
    state: dict[str, Any] | None = None


MATCHERS: list[MatcherSpec] = [
    # ---- 通知事件 ----
    MatcherSpec(
        kind="notice",
        handler=add_notices,
        priority=5,
        block=False,
    ),
    MatcherSpec(
        kind="notice",
        handler=poke_event,
        priority=5,
        block=False,
    ),
    MatcherSpec(
        kind="notice",
        handler=recall,
        priority=5,
        block=False,
    ),
    # ---- 消息事件：处理聊天消息 ----
    MatcherSpec(
        kind="message",
        handler=chat,
        block=False,
        priority=11,
        rule=Rule(should_respond_with_usage_check, is_bot_enabled),
    ),
    # ---- 模型域 ----
    MatcherSpec(
        command="model",
        aliases={"模型", "切换模型", "模型管理"},
        priority=10,
        block=True,
        permission=is_bot_admin,
        handler=model,
        state=MatcherData(
            name="模型管理",
            description="查看、切换与测试模型",
            show_if="lp.admin",
            usage=[
                "/model — 查看当前模型",
                "/model list — 可用模型",
                "/model switch <名> — 切换",
                "/model info — 当前详情",
                "/model test [名] [-d] — 测试",
            ],
        ).model_dump(),
    ),
    # ---- 提示词域 ----
    MatcherSpec(
        command="prompt",
        priority=10,
        block=True,
        permission=is_group_admin_if_is_in_group,
        handler=prompt,
        state=MatcherData(
            name="提示词管理",
            description="设置自定义提示词与切换模板",
            usage=[
                "/prompt — 查看",
                "/prompt set <文本> — 设置",
                "/prompt clear — 清空",
                "/prompt template [group|private] [名称] — 模板",
            ],
        ).model_dump(),
    ),
    # ---- 会话域 ----
    MatcherSpec(
        command="session",
        aliases={"会话", "会话管理"},
        priority=10,
        block=True,
        force_whitespace=True,
        permission=is_group_admin_if_is_in_group,
        handler=session,
        state=MatcherData(
            name="会话管理",
            description="会话信息、历史、压缩与记忆管理",
            usage=[
                "/session info — 元信息",
                "/session list — 历史",
                "/session use <编号> — 恢复",
                "/session del <编号> — 删除",
                "/session archive — 归档",
                "/session clear — 清空",
                "/session compact [force] — 压缩",
                "/session forget — 清除记忆",
                "/session abstract [clear] — 摘要",
            ],
        ).model_dump(),
    ),
    # ---- 聊天开关域 ----
    MatcherSpec(
        command="chat",
        aliases={"聊天开关", "chat_switch"},
        priority=10,
        block=True,
        permission=is_group_admin,
        group=chat_switch_matcher,
        handler=chat_switch,
        state=MatcherData(
            name="聊天开关",
            description="开启/关闭聊天与自动回复",
            usage=[
                "/chat — 状态",
                "/chat on|off — 聊天开关",
                "/chat auto <on|off> — 自动回复",
                "/chat status — 状态",
            ],
        ).model_dump(),
    ),
    # ---- 调试 ----
    MatcherSpec(
        command="debug",
        priority=10,
        block=True,
        permission=is_bot_admin,
        handler=debug_switchs,
        state=MatcherData(
            name="调试模式",
            description="调试模式开关（on/off/status）",
            show_if="lp.admin",
            usage=[
                "/debug on — 开启调试",
                "/debug off — 关闭调试",
                "/debug status — 查看状态",
            ],
        ).model_dump(),
    ),
    # ---- 用量统计 ----
    MatcherSpec(
        command="insights",
        aliases={"今日用量"},
        block=True,
        priority=10,
        handler=insights,
        state=MatcherData(
            name="用量统计",
            description="查看今日AI用量统计",
            usage=[
                "/insights — 查看今日用量",
                "/insights global — 全局用量",
                "/insights top10 <--group|private|all> — Top10 排名",
            ],
        ).model_dump(),
    ),
    # ---- MCP 管理 ----
    MatcherSpec(
        command="mcp",
        aliases={"MCP管理"},
        permission=is_bot_admin,
        handler=mcp_command,
        state=MatcherData(
            name="mcp",
            description="管理MCP服务",
            show_if="lp.admin",
            usage=[
                "/mcp stats [-d|--details] — 服务统计",
                "/mcp add <server_script> — 添加服务",
                "/mcp del <server_script> — 删除服务",
                "/mcp reload — 重载服务",
                "/mcp deep-reload — 深度重载",
            ],
        ).model_dump(),
    ),
    # ---- 会话进程管理 ----
    MatcherSpec(
        command="chatobj",
        aliases={"chat_obj"},
        permission=is_group_admin_if_is_in_group,
        handler=chatobj_manage,
        state=MatcherData(
            name="chatobj",
            description="管理聊天对话",
            usage=[
                "/chatobj - 显示所有会话状态",
                "/chatobj status - 显示所有会话状态",
                "/chatobj terminate <ID前缀> - 终止指定会话",
                "/chatobj kill <ID前缀> - 终止指定会话",
                "/chatobj clear - 清除已完成的会话",
            ],
        ).model_dump(),
    ),
]


def _register(spec: MatcherSpec) -> None:
    """按规格注册单个匹配器"""
    group = spec.group or base_matcher
    kwargs: dict[str, Any] = {}
    if spec.priority is not None:
        kwargs["priority"] = spec.priority
    if spec.block is not None:
        kwargs["block"] = spec.block
    if spec.permission is not None:
        kwargs["permission"] = spec.permission

    if spec.kind == "notice":
        matcher = group.on_notice(**kwargs)
    elif spec.kind == "message":
        if spec.rule is not None:
            kwargs["rule"] = spec.rule
        matcher = group.on_message(**kwargs)
    else:
        assert spec.command is not None, "command 类匹配器必须提供 command"
        kwargs["aliases"] = spec.aliases
        # 仅当显式指定时才传入，避免 False 覆盖 NoneBot 默认的 None
        # （NoneBot 中 force_whitespace=False 表示命令后必须无空白，
        #  会导致 `/chat on` 这类带空格参数的命令静默失配）
        if spec.force_whitespace is not None:
            kwargs["force_whitespace"] = spec.force_whitespace
        kwargs["state"] = spec.state
        matcher = group.on_command(spec.command, **kwargs)
    matcher.append_handler(spec.handler)


for _spec in MATCHERS:
    _register(_spec)
