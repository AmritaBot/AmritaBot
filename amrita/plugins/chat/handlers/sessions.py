from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime

from amrita_core.types import MemoryModel as AwaredMemory
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.exception import NoneBotException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot_plugin_amrita.database import UserDataExecutor
from nonebot_plugin_amrita.memory import CachedUserDataRepository, MemorySessionsSchema
from nonebot_plugin_orm import get_session

from ..check_rule import is_group_admin_if_is_in_group
from ..config import config_manager
from ..utils.sql import get_uni_user_id


async def sessions(
    bot: Bot, event: MessageEvent, matcher: Matcher, args: Message = CommandArg()
):
    """会话管理命令处理入口"""
    if not await is_group_admin_if_is_in_group(event, bot):
        await matcher.finish("你没有权限执行此命令。")

    # 获取用户唯一ID
    uni_user_id = get_uni_user_id(event)
    repo = CachedUserDataRepository()

    async def display_sessions(sessions: Sequence[MemorySessionsSchema]) -> None:
        """显示历史会话列表"""
        if not sessions:
            await matcher.finish("没有历史会话")
        message_content = "历史会话\n"
        for index, msg in enumerate(sessions):
            if msg.data.messages:
                message_content += f"编号：{index}) ：{msg.data.abstract[:15] or '（无描述）'}... 时间：{datetime.fromtimestamp(msg.created_at).strftime('%Y-%m-%d %I:%M:%S %p')}\n"
        await matcher.finish(message_content)

    async def set_session(
        arg_list: list[str],
    ) -> None:
        """将当前会话覆盖为指定编号的会话"""
        try:
            if len(arg_list) >= 2:
                # 获取用户的所有会话数据
                user_sessions = await repo.get_sesssions(get_uni_user_id(event))

                session_index = int(arg_list[1])
                if session_index < 0 or session_index >= len(user_sessions):
                    await matcher.finish("请输入正确的编号")

                # 获取指定编号的会话数据
                target_session = user_sessions[session_index]

                # 获取当前用户的memory数据并更新
                memory_data = await repo.get_memory(get_uni_user_id(event))
                memory_data.memory_json.messages = deepcopy(
                    target_session.data.messages
                )

                # 保存更新后的memory数据
                await repo.update_memory_data(memory_data)
                await matcher.send("完成记忆覆盖。")
            else:
                await matcher.finish("请输入正确编号")
        except NoneBotException as e:
            raise e
        except (ValueError, IndexError):
            await matcher.finish("请输入正确的编号")
        except Exception as e:
            logger.opt(exception=e, colors=True, raw=True).exception(
                "覆盖记忆文件失败。"
            )
            await matcher.finish("覆盖记忆文件失败，这个对话可能损坏了。")

    async def delete_session(
        arg_list: list[str],
    ) -> None:
        """删除指定编号的会话"""
        try:
            if len(arg_list) >= 2:
                session_index = int(arg_list[1])

                # 获取用户的所有会话数据
                user_sessions = await repo.get_sesssions(get_uni_user_id(event))

                if session_index < 0 or session_index >= len(user_sessions):
                    await matcher.finish("请输入正确的编号")
                user_sessions_list = list(user_sessions)
                removed_session = user_sessions_list.pop(session_index)
                # 从数据库中删除
                async with get_session() as session:
                    async with UserDataExecutor(uni_user_id, session) as executor:
                        await executor.remove_session(removed_session.id)

                await matcher.send("已删除对应的会话。")
            else:
                await matcher.finish("请输入正确编号")
        except NoneBotException as e:
            raise e
        except (ValueError, IndexError):
            await matcher.finish("请输入正确的编号")
        except Exception as e:
            logger.opt(exception=e, colors=True, raw=True).exception(
                "删除指定编号会话失败。"
            )
            await matcher.finish("删除指定编号会话失败。")

    async def archive_session() -> None:
        """归档当前会话"""
        try:
            # 获取当前用户记忆数据
            memory_data = await repo.get_memory(get_uni_user_id(event))

            if memory_data.memory_json.messages:
                # 获取当前会话数据
                current_messages = memory_data.memory_json.messages
                current_abstract = memory_data.memory_json.abstract

                # 创建新会话并保存到数据库
                new_session_data = AwaredMemory(
                    messages=deepcopy(current_messages), abstract=current_abstract
                )

                async with get_session() as session:
                    async with UserDataExecutor(uni_user_id, session) as executor:
                        await executor.add_session(new_session_data)
                # 清空当前记忆中的消息
                memory_data.memory_json.messages = []
                await repo.update_memory_data(memory_data)

                await matcher.finish("当前会话已归档。")
            else:
                await matcher.finish("当前对话为空！")
        except NoneBotException as e:
            raise e
        except Exception as e:
            logger.opt(exception=e, colors=True, raw=True).exception(
                "归档当前会话失败。"
            )
            await matcher.finish("归档当前会话失败。")

    async def clear_sessions() -> None:
        """清空所有会话"""
        try:
            # 获取用户的所有会话
            user_sessions = await repo.get_sesssions(get_uni_user_id(event))

            if len(user_sessions) > 0:
                # 获取会话ID列表
                session_ids = [session.id for session in user_sessions]

                # 从数据库中删除所有会话
                async with get_session() as session:
                    async with UserDataExecutor(uni_user_id, session) as executor:
                        await executor.remove_session(*session_ids)

            await matcher.finish("会话已清空。")
        except NoneBotException as e:
            raise e
        except Exception:
            logger.exception("清除当前会话失败。")
            await matcher.finish("清空当前会话失败。")

    # 检查是否启用了会话管理功能
    if not config_manager.config.session.session_control:
        matcher.skip()
    # 解析用户输入的命令参数
    arg_list = args.extract_plain_text().strip().split()

    # 如果没有参数，显示历史会话
    if not arg_list:
        user_sessions = await repo.get_sesssions(get_uni_user_id(event))
        await display_sessions(user_sessions)

    # 根据命令执行对应操作
    match arg_list[0]:
        case "set":
            await set_session(
                arg_list,
            )
        case "del":
            await delete_session(
                arg_list,
            )
        case "archive":
            await archive_session()
        case "clear":
            await clear_sessions()
        case "help":
            await matcher.finish(
                "Sessions指令帮助：\nset：覆盖当前会话为指定编号的会话\ndel：删除指定编号的会话\narchive：归档当前会话\nclear：清空所有会话\n"
            )
        case "list":
            user_sessions = await repo.get_sesssions(get_uni_user_id(event))
            await display_sessions(user_sessions)
        case _:
            await matcher.finish("未知命令，请输入/help查看帮助。")
