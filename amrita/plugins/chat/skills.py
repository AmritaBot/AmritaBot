"""faskill Skills 集成服务。

技能目录与 model preset 目录（``config/chat/models/``）同级，即
``config/chat/skills/``；每个技能以标准 ``SKILL.md`` 格式描述，由 faskill
发现、加载与调用（Anthropic Agent Skills 兼容）。

工具池注入方式（关键约束）：

- ``load_tools`` 通过数据后端（``NoopAbilityBackend``）构建会话级工具池：
  以全局 ``ToolsManager`` 单例为基底**克隆**（copy+mixin），再把技能工具
  混合进克隆返回——既保留全局工具池全部工具，又不污染全局单例；
- 技能工具的 handler 采用 ``custom_run=True`` 自定义执行：调用技能前通过
  ``io_stream`` 推送 ``type="skill_call"`` 元信息消息，由 chat 的 sender
  按 ``[meta]`` 配置决定是否发送"使用了xxx技能"的通知；
- 启停过滤：``[skills]`` 配置（enable/enabled/disabled）决定哪些技能被注册
  进工具池、写入 system prompt 使用指引；
- 加载校验：``validate_skills`` 在插件启动时尽力解析/加载全部技能并返回
  状态列表（单个技能失败仅记录日志，不阻断启动），供 WebUI 展示。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from amrita_core.contents import MessageMetadataPayload, MessageWithMetadata
from amrita_core.tools.manager import MultiToolsManager, ToolsManager
from amrita_core.tools.models import (
    FunctionDefinitionSchema,
    FunctionParametersSchema,
    FunctionPropertySchema,
    ToolContext,
    ToolData,
    ToolFunctionSchema,
)
from faskill import SkillContext, create_context
from faskill.integrations.amcore import (
    clone_tools_manager,
    register_amrita_script_tools,
)
from nonebot import logger

from .config import CONFIG_DIR, config_manager

# 技能目录：与 model preset 目录（config/chat/models/）同级
SKILLS_DIR: Path = CONFIG_DIR / "skills"

# 技能工具的唯一参数名：用户请求原文透传（经 $ARGUMENTS 注入模板）
_ARGUMENTS_PARAM = "arguments"

_skill_context: SkillContext | None = None


class SkillCallMetadata(MessageMetadataPayload):
    """技能触发元信息载荷（type=skill_call）"""

    skill_name: str


@dataclass
class SkillValidationResult:
    """单个技能的加载校验结果"""

    name: str
    description: str
    version: str | None
    path: str
    enabled: bool
    ok: bool
    error: str | None


def get_skill_context() -> SkillContext:
    """返回模块级缓存的 ``SkillContext``（首次调用时 discover）。

    技能目录不存在时自动创建（faskill 要求目录存在）；目录为空时
    技能列表为空，``build_skill_usage_prompt`` 返回空字符串。
    """
    global _skill_context
    if _skill_context is None:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        ctx = create_context(skill_dirs=[SKILLS_DIR])
        ctx.discover()
        _skill_context = ctx
    return _skill_context


def _skill_enabled(name: str) -> bool:
    """按 ``[skills]`` 配置判断技能是否启用。

    配置未就绪（插件启动早期）时视为启用；黑名单优先级高于白名单。
    """
    cfg = getattr(config_manager, "ins_config", None)
    skills_cfg = getattr(cfg, "skills", None)
    if skills_cfg is None:
        return True
    if not skills_cfg.enable:
        return False
    if name in skills_cfg.disabled:
        return False
    if skills_cfg.enabled and name not in skills_cfg.enabled:
        return False
    return True


def _build_arguments_schema(name: str, description: str) -> ToolFunctionSchema:
    """构建单参数（arguments 字符串）技能工具 schema（与 faskill 一致）。"""
    return ToolFunctionSchema(
        type="function",
        strict=True,
        function=FunctionDefinitionSchema(
            name=name,
            description=description,
            parameters=FunctionParametersSchema(
                type="object",
                properties={
                    _ARGUMENTS_PARAM: FunctionPropertySchema(
                        type="string",
                        description=(
                            "Arguments to pass to the skill (empty string if none)"
                        ),
                    ),
                },
                required=[_ARGUMENTS_PARAM],
            ),
        ),
    )


def _make_skill_handler(
    ctx: SkillContext,
    skill_name: str,
    tools: MultiToolsManager,
):
    """构建 ``custom_run=True`` 技能工具 handler。

    职责：
    1. 调用前通过 ``io_stream`` 推送 ``type="skill_call"`` 元信息消息
       （sender 按 ``meta.skill_trigger`` 决定是否发送"使用了xxx技能"）；
    2. 在工作线程执行技能（同步 API，避免阻塞事件循环）；
    3. 渐进披露 L3：技能被调用后将其脚本工具注册进同一会话工具池。
    """

    async def invoke_skill(tc: ToolContext) -> str:
        arguments = tc.data.get(_ARGUMENTS_PARAM, "")
        if arguments is None:
            arguments = ""

        # 技能触发元信息消息（chat sender 依据 [meta] 配置决定是否展示）
        stream = tc.ctx.io_stream
        if stream is not None:
            try:
                await stream.yield_response(
                    MessageWithMetadata(
                        content=f"使用了技能：{skill_name}",
                        metadata=SkillCallMetadata(
                            type="skill_call",
                            extra_type=None,
                            skill_name=skill_name,
                        ),
                    )
                )
            except Exception:
                logger.opt(exception=True, colors=True, raw=True).warning(
                    "推送技能触发元信息失败: %s", skill_name
                )

        # 执行技能（同步 API 放工作线程，避免阻塞事件循环）
        result = await asyncio.to_thread(ctx.invoke_skill, skill_name, str(arguments))

        # 渐进披露 L3：技能被调用后，其脚本工具注入同一会话工具池
        try:
            skill = ctx.load_skill(skill_name)
            if skill.scripts:
                register_amrita_script_tools(
                    skill, ctx, tools_manager=tools, copy=False
                )
        except Exception:
            logger.opt(exception=True, colors=True, raw=True).debug(
                "技能脚本工具激活失败: %s", skill_name
            )

        return result

    return invoke_skill


def build_skill_tools() -> MultiToolsManager:
    """构建会话级技能工具池（copy+mixin + 启停过滤 + 触发元信息推送）。

    以全局 ``ToolsManager()`` 单例为基底克隆其注册表（``copy=True``），
    再把**启用**的技能工具（``custom_run=True`` handler）混合进克隆返回：
    返回的工具池包含全局工具池的全部工具，且注册技能不会改写全局单例。

    progressive disclosure：技能被模型调用时，其脚本工具才注入同一管理器。
    由数据后端 ``load_tools`` 每次会话抓取。
    """
    ctx = get_skill_context()
    # copy+mixin：克隆全局注册表，保留全部全局工具且不污染单例
    tools = clone_tools_manager(ToolsManager())
    for meta in ctx.list_skills(include_qualified=False):
        if not _skill_enabled(meta.name):
            continue
        if tools.has_tool(meta.name):
            continue
        tools.register_tool(
            ToolData(
                data=_build_arguments_schema(meta.name, meta.description),
                func=_make_skill_handler(ctx, meta.name, tools),
                custom_run=True,
            )
        )
    return tools


def build_skill_usage_prompt() -> str:
    """构建 system prompt 技能使用指引（过滤禁用技能；无可用技能返回空串）。"""
    ctx = get_skill_context()
    skills = [
        meta
        for meta in ctx.list_skills(include_qualified=False)
        if _skill_enabled(meta.name)
    ]
    if not skills:
        return ""
    lines = [
        "## Available faskill skills",
        "Call a skill tool when the user's task matches its purpose:",
    ]
    lines.extend(f"- {meta.name}: {meta.description}" for meta in skills)
    lines.append(
        "Call a skill tool when the user's task matches its purpose. "
        'Pass the user\'s request as the "arguments" string; it is inserted '
        "into the skill template via $ARGUMENTS. "
        "The tool returns the processed skill output (markdown)."
    )
    return "\n".join(lines)


def validate_skills() -> list[SkillValidationResult]:
    """加载并校验技能目录中的全部技能（尽力而为，不阻断启动）。

    discover 已尽力解析 SKILL.md frontmatter（失败仅记录日志）；这里对
    每个技能执行完整加载（触发正文解析），汇总状态供 WebUI 展示。
    """
    ctx = get_skill_context()
    results: list[SkillValidationResult] = []
    for meta in ctx.list_skills(include_qualified=False):
        error: str | None = None
        ok = True
        try:
            ctx.load_skill(meta.name)
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}"
            logger.opt(exception=e, colors=True, raw=True).warning(
                "技能加载校验失败: %s", meta.name
            )
        results.append(
            SkillValidationResult(
                name=meta.name,
                description=meta.description,
                version=meta.version,
                path=str(meta.skill_path),
                enabled=_skill_enabled(meta.name),
                ok=ok,
                error=error,
            )
        )
    return results


def reload_skills() -> list[SkillValidationResult]:
    """重新 discover 并校验全部技能（拾取新增/修改的技能文件）。

    丢弃模块级缓存的 ``SkillContext`` 并重新发现：修改 SKILL.md 后调用
    可让新增/更新的技能立即生效（下次构建工具池时按新列表注册）。
    """
    global _skill_context
    _skill_context = None
    return validate_skills()
