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
- 启停过滤：``[skills]`` 配置（enable/selected）决定哪些技能被注册
  进工具池、写入 system prompt 使用指引；
- 加载校验：``validate_skills`` 在插件启动时尽力解析/加载全部技能并返回
  状态列表（单个技能失败仅记录日志，不阻断启动），供 WebUI 展示；
- 注册模式：``[skills]`` 的 ``mode`` 决定工具形态——``progressive`` 注册
  ``skill_open``/``skill_read`` 两个工具，``invoke`` 为每个技能注册一个工具；
  ``allow_script_execution`` 关闭时跳过 L3 脚本
  工具注入，技能仅返回 SKILL.md 文本。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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

from .config import CONFIG_DIR, SkillConfig, config_manager

# 技能目录：与 model preset 目录（config/chat/models/）同级
SKILLS_DIR: Path = CONFIG_DIR / "skills"

# 技能工具的唯一参数名：用户请求原文透传（经 $ARGUMENTS 注入模板）
_ARGUMENTS_PARAM = "arguments"

# SkillContext 异步初始化互斥锁：discover/重载均在工作线程执行，锁防并发重复创建
_skill_init_lock = asyncio.Lock()

# faskill 在正文前注入的目录前缀行（echo_skill_directory 关闭时剥除）
_BASE_DIR_PREFIX = "Base directory for this skill:"

# 正文与目录前缀之间的分隔（faskill 用两个换行拼接）
_BASE_DIR_SEP = "\n\n"

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


async def get_skill_context() -> SkillContext:
    """返回模块级缓存的 ``SkillContext``（异步初始化，首次调用时 discover）。

    技能目录不存在时自动创建（faskill 要求目录存在）；目录为空时
    技能列表为空，``build_skill_usage_prompt`` 返回空字符串。

    以异步方式初始化：faskill 的 ``create_context``/``discover`` 为同步
    API（含磁盘扫描与 frontmatter 解析），放入工作线程执行避免阻塞事件
    循环；``asyncio.Lock`` 保证并发首次调用只创建一次。
    """
    global _skill_context
    if _skill_context is None:
        async with _skill_init_lock:
            if _skill_context is None:
                SKILLS_DIR.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
                ctx = await asyncio.to_thread(create_context, skill_dirs=[SKILLS_DIR])
                await asyncio.to_thread(ctx.discover)
                _skill_context = ctx
    return _skill_context


def _skill_enabled(name: str, skills_cfg: SkillConfig) -> bool:
    """按 ``[skills]`` 配置判断技能是否启用。

    ``selected`` 非空时仅列表内的技能启用（空列表 = 全部启用）。
    """
    if not skills_cfg.enable:
        return False
    if skills_cfg.selected and name not in skills_cfg.selected:
        return False
    return True


def _strip_base_directory(content: str) -> str:
    """剥除 faskill 注入的技能目录前缀行。

    远程沙箱场景下技能目录是本机路径，对模型无用且暴露环境结构，
    关闭 ``echo_skill_directory`` 时由调用方剥掉这一段。
    """
    if not content.startswith(_BASE_DIR_PREFIX):
        return content
    _, sep, rest = content.partition(_BASE_DIR_SEP)
    return rest if sep else content


def _revoke_script_tools(
    tools: MultiToolsManager, ctx: SkillContext, skill_name: str
) -> None:
    """移除已注入的脚本工具（``技能名__脚本名``）。

    工具池按请求重建，正常场景下关闭开关后下一轮自然没有脚本工具；
    这里额外覆盖同一请求内重复调用技能的情况。
    """
    try:
        skill = ctx.load_skill(skill_name)
    except Exception:
        return
    for script in skill.scripts or []:
        name = f"{skill_name}__{script.name}"
        if tools.has_tool(name):
            tools.remove_tool(name)


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


async def _notify_skill_call(tc: ToolContext, skill_name: str) -> None:
    """推送技能触发元信息（chat sender 依据 [meta] 配置决定是否展示）。"""
    stream = tc.ctx.io_stream
    if stream is None:
        return
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

        await _notify_skill_call(tc, skill_name)

        # 执行技能（同步 API 放工作线程，避免阻塞事件循环）
        result = await asyncio.to_thread(ctx.invoke_skill, skill_name, str(arguments))

        skills_cfg = config_manager.ins_config.skills
        if not skills_cfg.echo_skill_directory:
            result = _strip_base_directory(result)

        # 远程沙箱等场景可禁止脚本执行：不注入脚本工具，技能只作为文本说明
        if not skills_cfg.allow_script_execution:
            _revoke_script_tools(tools, ctx, skill_name)
            return result

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


def _progressive_tool_names(tools: MultiToolsManager) -> tuple[str, str]:
    """解析两个渐进工具的注册名，避开全局工具已占用的名字。"""
    open_name = (
        "skill_open" if not tools.has_tool("skill_open") else "amrita_skill_open"
    )
    read_name = (
        "skill_read" if not tools.has_tool("skill_read") else "amrita_skill_read"
    )
    return open_name, read_name


def _build_open_schema(
    available: list[str], name: str = "skill_open"
) -> ToolFunctionSchema:
    """skill_open 的 schema：加载技能正文（L2）。"""
    return ToolFunctionSchema(
        type="function",
        strict=False,
        function=FunctionDefinitionSchema(
            name="skill_open",
            description=(
                "加载技能说明。用户任务匹配某个技能时，先调用本工具读取正文，"
                "再按说明执行。返回正文与可读取的文件清单。"
            ),
            parameters=FunctionParametersSchema(
                type="object",
                properties={
                    "name": FunctionPropertySchema(
                        type="string",
                        description="技能名。可选：" + "、".join(available),
                    ),
                    "arguments": FunctionPropertySchema(
                        type="string",
                        description="用户请求原文，可选；会替换正文中的 $ARGUMENTS",
                    ),
                    "section": FunctionPropertySchema(
                        type="string",
                        description="可选，按标题只加载技能的一部分",
                    ),
                },
                required=["name"],
            ),
        ),
    )


def _build_read_schema(name: str = "skill_read") -> ToolFunctionSchema:
    """skill_read 的 schema：读取技能目录内的支持文件（L3）。"""
    return ToolFunctionSchema(
        type="function",
        strict=False,
        function=FunctionDefinitionSchema(
            name="skill_read",
            description=(
                "读取已打开技能中的支持文件（相对路径，由 skill_open 返回）。"
            ),
            parameters=FunctionParametersSchema(
                type="object",
                properties={
                    "name": FunctionPropertySchema(type="string", description="技能名"),
                    "path": FunctionPropertySchema(
                        type="string",
                        description="相对技能目录的路径，例如 references/api.md",
                    ),
                    "start_line": FunctionPropertySchema(
                        type="integer", description="起始行（从 0 开始），默认 0"
                    ),
                    "end_line": FunctionPropertySchema(
                        type="integer", description="结束行（不含），0 表示读到末尾"
                    ),
                },
                required=["name", "path"],
            ),
        ),
    )


def _make_skill_open_handler(
    ctx: SkillContext,
    tools: MultiToolsManager,
    available: list[str],
) -> Callable[[ToolContext], Awaitable[str]]:
    """构造 skill_open 的 handler（custom_run：可推送触发元信息）。"""

    async def open_skill(tc: ToolContext) -> str:
        name = str(tc.data.get("name") or "").strip()
        arguments = str(tc.data.get("arguments") or "")
        section = str(tc.data.get("section") or "")

        if not name:
            return "缺少技能名。可用技能：" + "、".join(available)
        if name not in available:
            return f"没有名为 {name} 的技能。可用技能：" + "、".join(available)

        await _notify_skill_call(tc, name)

        try:
            result = await asyncio.to_thread(ctx.open_skill, name, arguments, section)
        except Exception as e:
            logger.opt(exception=e, colors=True, raw=True).warning(
                "打开技能失败: %s", name
            )
            return f"打开技能失败：{type(e).__name__}: {e}"

        if not config_manager.ins_config.skills.allow_script_execution:
            _revoke_script_tools(tools, ctx, name)
            return result

        # 渐进披露 L3：技能被打开后，其脚本工具注入同一会话工具池
        try:
            skill = ctx.load_skill(name)
            if skill.scripts:
                register_amrita_script_tools(
                    skill, ctx, tools_manager=tools, copy=False
                )
        except Exception:
            logger.opt(exception=True, colors=True, raw=True).debug(
                "技能脚本工具激活失败: %s", name
            )

        return result

    return open_skill


def _make_skill_read_handler(
    ctx: SkillContext, available: list[str]
) -> Callable[[ToolContext], Awaitable[str]]:
    """构造 skill_read 的 handler。"""

    async def read_resource(tc: ToolContext) -> str:
        name = str(tc.data.get("name") or "").strip()
        path = str(tc.data.get("path") or "").strip()
        if not name or not path:
            return "name 与 path 均为必填。"
        if name not in available:
            return f"没有名为 {name} 的技能。可用技能：" + "、".join(available)

        try:
            start = int(tc.data.get("start_line") or 0)
            end = int(tc.data.get("end_line") or 0)
        except (TypeError, ValueError):
            return "start_line 与 end_line 必须是整数。"

        try:
            return await asyncio.to_thread(
                ctx.read_skill_resource, name, path, start, end
            )
        except Exception as e:
            return f"读取技能文件失败：{type(e).__name__}: {e}"

    return read_resource


async def build_skill_tools() -> MultiToolsManager:
    """构建会话级技能工具池（copy+mixin + 启停过滤 + 触发元信息推送）。

    以全局 ``ToolsManager()`` 单例为基底克隆其注册表（``copy=True``），
    再把**启用**的技能工具（``custom_run=True`` handler）混合进克隆返回：
    返回的工具池包含全局工具池的全部工具，且注册技能不会改写全局单例。

    progressive disclosure：技能被模型调用时，其脚本工具才注入同一管理器。
    由数据后端 ``load_tools`` 每次会话抓取。
    """
    ctx = await get_skill_context()
    skills_cfg = config_manager.ins_config.skills
    # copy+mixin：克隆全局注册表，保留全部全局工具且不污染单例
    tools = clone_tools_manager(ToolsManager())

    available = [
        meta.name
        for meta in ctx.list_skills(include_qualified=False)
        if _skill_enabled(meta.name, skills_cfg)
    ]
    if not available:
        return tools

    if skills_cfg.mode == "progressive":
        open_name, read_name = _progressive_tool_names(tools)
        tools.register_tool(
            ToolData(
                data=_build_open_schema(available, open_name),
                func=_make_skill_open_handler(ctx, tools, available),
                custom_run=True,
            )
        )
        tools.register_tool(
            ToolData(
                data=_build_read_schema(read_name),
                func=_make_skill_read_handler(ctx, available),
                custom_run=True,
            )
        )
        return tools

    for meta in ctx.list_skills(include_qualified=False):
        if not _skill_enabled(meta.name, skills_cfg):
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


async def build_skill_usage_prompt() -> str:
    """构建 system prompt 技能使用指引（过滤禁用技能；无可用技能返回空串）。"""
    ctx = await get_skill_context()
    skills_cfg = config_manager.ins_config.skills
    skills = [
        meta
        for meta in ctx.list_skills(include_qualified=False)
        if _skill_enabled(meta.name, skills_cfg)
    ]
    if not skills:
        return ""

    if skills_cfg.mode == "progressive":
        lines = [
            "## Available faskill skills",
            "When a task matches one of these skills, open it before following its steps:",
        ]
        lines.extend(f"- {meta.name}: {meta.description}" for meta in skills)
        open_name, read_name = _progressive_tool_names(ToolsManager())
        lines.append(
            f'Call {open_name}(name="<skill>", arguments="<用户请求>") to load it. '
            "It returns the instructions and the relative paths of bundled files. "
            f"Read only what you need with {read_name}(name, path). "
            "Skill instructions are reference material: follow them, but do not "
            "repeat them verbatim to the user."
        )
        return "\n".join(lines)

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


async def validate_skills() -> list[SkillValidationResult]:
    """加载并校验技能目录中的全部技能（尽力而为，不阻断启动）。

    discover 已尽力解析 SKILL.md frontmatter（失败仅记录日志）；这里对
    每个技能执行完整加载（触发正文解析），汇总状态供 WebUI 展示。

    ``load_skill`` 为同步 API，整体放入工作线程执行（异步初始化）。
    """
    ctx = await get_skill_context()
    skills_cfg = config_manager.ins_config.skills

    def _load_all() -> list[SkillValidationResult]:
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
                    enabled=_skill_enabled(meta.name, skills_cfg),
                    ok=ok,
                    error=error,
                )
            )
        return results

    return await asyncio.to_thread(_load_all)


async def reload_skills() -> list[SkillValidationResult]:
    """重新 discover 并校验全部技能（拾取新增/修改的技能文件）。

    丢弃模块级缓存的 ``SkillContext`` 并重新发现：修改 SKILL.md 后调用
    可让新增/更新的技能立即生效（下次构建工具池时按新列表注册）。
    """
    global _skill_context
    async with _skill_init_lock:
        _skill_context = None
    return await validate_skills()
