import contextlib

from amrita_core.tools.mcp import ClientManager
from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from amrita.plugins.chat.config import config_manager
from amrita.plugins.chat.utils.mcp_boot import (
    configured_scripts,
    find_state,
    list_states,
    load_mcp_servers,
    operation_lock,
    reload_mcp_servers,
    remove_state,
)
from amrita.utils.send import send_forward_msg


async def mcp_command(
    bot: Bot, matcher: Matcher, event: MessageEvent, arg: Message = CommandArg()
):
    arg_list = arg.extract_plain_text().strip().split(maxsplit=1)
    match len(arg_list):
        case 0:
            await matcher.finish(
                "❌ 缺少参数！\n可用：\n\n"
                "   stats [-d|--details]\n"
                "   add <server_script>\n"
                "   del <server_script>\n"
                "   reload\n"
                "   deep-reload"
            )
        case 1 | 2:
            if arg_list[0] == "stats":
                return await mcp_status(bot, matcher, event, arg_list[1:])
            elif arg_list[0] == "reload":
                return await reload(matcher)
            elif arg_list[0].replace("_", "-") == "deep-reload":
                return await deep_reload(matcher)
            elif len(arg_list) == 2:
                if arg_list[0] in ("add", "添加"):
                    return await add_mcp_server(matcher, bot, event, arg_list[1])
                elif arg_list[0] in ("del", "删除"):
                    return await del_mcp_server(matcher, arg_list[1])

    await matcher.finish("参数数量或类型错误，请检查命令格式。")


async def mcp_status(bot: Bot, matcher: Matcher, event: MessageEvent, arg: list[str]):
    arg_text = arg[0] if arg else ""
    states = list_states()
    tools_count = len(ClientManager().name_to_clients)
    mcp_server_counts = len(states)
    tools_mapping_count = len(ClientManager().tools_remapping)
    lines = [
        "MCP状态统计",
        f"MCP Servers: {mcp_server_counts}",
        f"MCP Tools: {tools_count}",
        f"MCP Tools(Mapped): {tools_mapping_count}",
    ]
    for state in states:
        mark = "✅" if state.status == "connected" else "❌"
        detail = (
            f"{len(state.tools)} 个工具" if state.status == "connected" else state.error
        )
        lines.append(f"{mark} {state.id} {state.script}（{detail}）")
    std_txt = "\n".join(lines)
    if arg_text in ("-d", "--detail", "--details"):
        if not isinstance(event, PrivateMessageEvent):
            await matcher.finish("-d只允许在私聊执行来避免安全问题")
        detailed_info = [
            MessageSegment.text(std_txt),
            *[
                MessageSegment.text(
                    f"Server@{client.server_script!s} Tools: \n".join(
                        [
                            f" - {tool.function.name}:{tool.function.description}\n"
                            for tool in client.openai_tools
                        ]
                    )
                )
                for client in ClientManager().clients
            ],
        ]

        await send_forward_msg(
            bot, event, "Amrita-MCP", str(event.self_id), detailed_info
        )
    else:
        await matcher.finish(std_txt)


async def add_mcp_server(
    matcher: Matcher, bot: Bot, event: MessageEvent, mcp_server: str
):
    config = config_manager.ins_config
    if not config.core.function_config.agent_mcp_client_enable:
        return
    if not mcp_server:
        await matcher.finish("请输入MCP Server脚本路径")
    async with operation_lock():
        #  error 状态只代表试过，不该挡住重试；已连上的才算重复
        state = find_state(mcp_server)
        if state is not None and state.status == "connected":
            await matcher.finish("MCP Server脚本已存在")
        report = await load_mcp_servers([mcp_server])
        if not report.failed:
            scripts = config.core.function_config.agent_mcp_server_scripts
            added = mcp_server not in scripts
            if added:
                scripts.append(mcp_server)
                try:
                    await config_manager.save_config()
                except Exception as e:
                    #  写盘失败就把刚连上的连接撤掉，别让运行态与配置分叉
                    logger.opt(exception=e).error("保存 MCP 配置失败")
                    with contextlib.suppress(Exception):
                        await ClientManager().unregister_client(mcp_server)
                    scripts.remove(mcp_server)
                    remove_state(mcp_server)
                    report.failed.append((mcp_server, "保存配置失败"))
    if report.failed:
        await matcher.send(f"添加失败：{report.failed[0][1]}")
        return
    state = find_state(mcp_server)
    await matcher.send(f"添加成功（{state.id if state else mcp_server}）")


async def del_mcp_server(matcher: Matcher, mcp_server: str):
    if not config_manager.config.core.function_config.agent_mcp_client_enable:
        return
    config = config_manager.ins_config
    if not mcp_server:
        await matcher.finish("请输入要删除的MCP Server（id 或脚本路径）")
    #  以运行时状态为准：配置里可能没有这条，但它连着、也占着工具名
    state = find_state(mcp_server)
    if state is None:
        await matcher.finish("MCP Server不存在")
    try:
        if state.status == "connected":
            async with operation_lock():
                await ClientManager().unregister_client(state.script)
        remove_state(state.id)
        scripts = config.core.function_config.agent_mcp_server_scripts
        if state.script in scripts:
            scripts.remove(state.script)
            await config_manager.save_config()
        await matcher.send(f"删除成功：{state.id} {state.script}")
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception(e)
        await matcher.finish("删除失败")


async def reload(matcher: Matcher):
    if not config_manager.ins_config.core.function_config.agent_mcp_client_enable:
        return
    #  以配置为准重连：启动时就失败、没有客户端在册的服务也会在这里被重试
    async with operation_lock():
        report = await reload_mcp_servers(configured_scripts())
    await matcher.send(f"重载{'成功' if report.ok else '部分失败'}：{report.summary()}")


async def deep_reload(matcher: Matcher):
    if not config_manager.ins_config.core.function_config.agent_mcp_client_enable:
        return
    async with operation_lock():
        report = await reload_mcp_servers(configured_scripts(), reset_remapping=True)
    await matcher.send(
        f"完全重载{'成功' if report.ok else '部分失败'}：{report.summary()}"
    )
