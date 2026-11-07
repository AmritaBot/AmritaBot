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
    MCPLoadReport,
    _describe,
    load_mcp_servers,
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
    tools_count = len(ClientManager().name_to_clients)
    mcp_server_counts = len(ClientManager().clients)
    tools_mapping_count = len(ClientManager().tools_remapping)
    std_txt = f"MCP状态统计\nMCP Servers: {mcp_server_counts}\nMCP Tools: {tools_count}\nMCP Tools(Mapped): {tools_mapping_count}"
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
    config = config_manager.config
    if not config.core.function_config.agent_mcp_client_enable:
        return
    if not mcp_server:
        await matcher.finish("请输入MCP Server脚本路径")
    if mcp_server in config.core.function_config.agent_mcp_server_scripts:
        await matcher.finish("MCP Server脚本已存在")
    try:
        await ClientManager().initialize_this(mcp_server, True)
        config.core.function_config.agent_mcp_server_scripts.append(mcp_server)
        await config_manager.save_config()
        await matcher.send("添加成功")
    except Exception as e:
        await matcher.send(f"添加失败: {e}")
        logger.opt(exception=e, colors=True, raw=True).exception(e)


async def del_mcp_server(matcher: Matcher, mcp_server: str):
    if not config_manager.config.core.function_config.agent_mcp_client_enable:
        return
    config = config_manager.ins_config
    if not mcp_server:
        await matcher.finish("请输入要删除的MCP Server")
    if mcp_server not in config.core.function_config.agent_mcp_server_scripts:
        await matcher.finish("MCP Server不存在")
    try:
        await ClientManager().unregister_client(mcp_server)
        config.core.function_config.agent_mcp_server_scripts.remove(mcp_server)
        await config_manager.save_config()
        await matcher.send("删除成功")
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).exception(e)
        await matcher.finish("删除失败")


async def reload(matcher: Matcher):
    if not config_manager.config.core.function_config.agent_mcp_client_enable:
        return
    client_manager = ClientManager()
    report = MCPLoadReport()
    for cl in (client_manager.clients).copy():
        script = str(cl.server_script)
        try:
            await client_manager.unregister_client(cl.server_script)
            await cl.close_no_wait()  # 虽然热重载，但是为了避免竞态，这里先把会话掐了
            cl.tools.clear()
            cl.openai_tools.clear()
            await cl.bound_to(client_manager)
        except Exception as e:
            #  单个服务重连失败不影响其余服务，继续处理下一个
            logger.opt(exception=e, colors=True, raw=True).warning(
                f"MCP Server@{script} 重载失败"
            )
            report.failed.append((script, _describe(e)))
        else:
            report.loaded.append(script)
    await matcher.send(f"重载{'成功' if report.ok else '部分失败'}：{report.summary()}")


async def deep_reload(matcher: Matcher):
    if not config_manager.config.core.function_config.agent_mcp_client_enable:
        return
    try:
        client_manager = ClientManager()
        for cl in (client_manager.clients).copy():
            await client_manager.unregister_client(cl.server_script)
            await cl.close_no_wait()  # 虽然热重载，但是为了避免竞态，这里先把会话掐了
            cl.tools.clear()
            cl.openai_tools.clear()
        report = await load_mcp_servers(
            list(config_manager.config.core.function_config.agent_mcp_server_scripts),
            manager=client_manager,
        )
        await matcher.send(
            f"完全重载{'成功' if report.ok else '部分失败'}：{report.summary()}"
        )
    except BaseException as e:
        logger.opt(exception=e, colors=True, raw=True).exception(e)
        await matcher.send("完全重载失败")
