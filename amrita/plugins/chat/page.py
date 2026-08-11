import copy
from typing import Any

import aiofiles
from amrita_core import ModelPreset
from amrita_core.tools.mcp import ClientManager
from amrita_core.types import ModelConfig, ThinkingConfig
from fastapi import Request
from nonebot import logger
from nonebot_plugin_amrita.database import InsightsModel

from amrita.plugins.chat.config import config_manager
from amrita.plugins.webui.API import JSONResponse
from amrita.plugins.webui.API import app as router

KEY_PLACEHOLDER = "••••••••"


@router.post("/api/chat/models")
async def create_model(request: Request):
    try:
        data: dict[str, Any] = await request.json()
        name = data.get("name")
        model = data.get("model", "")
        base_url = data.get("base_url", "")
        api_key = data.get("api_key", "")
        protocol = data.get("protocol", "__main__")
        config_data = data.get("config", {})
        thinking_data = data.get("thinking_config")
        if not name:
            return JSONResponse(
                {"success": False, "message": "缺少模型预设名称"}, status_code=400
            )
        thinking_cfg = ThinkingConfig(**thinking_data) if thinking_data else None
        preset = ModelPreset(
            name=name,
            model=model,
            base_url=base_url,
            api_key=api_key,
            protocol=protocol,
            config=ModelConfig(**config_data),
            thinking_config=thinking_cfg,
        )

        # 保存模型预设到文件
        preset_path = config_manager.custom_models_dir / f"{name}.json"
        preset.save(preset_path)

        # 重新加载模型列表
        await config_manager.get_all_presets(cache=False)

        return JSONResponse(
            {"success": True, "message": f"模型预设 {name} 创建成功"}, status_code=200
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("创建模型预设失败")
        return JSONResponse(
            {"success": False, "message": f"创建模型预设失败: {e!s}"},
            status_code=500,
        )


@router.post("/api/chat/models/{name}")
async def update_model(request: Request, name: str):
    try:
        # 获取现有的模型预设
        preset = await config_manager.get_preset(name, fix=False, cache=False)

        if not preset:
            return JSONResponse(
                {"success": False, "message": f"模型预设 {name} 不存在"},
                status_code=404,
            )

        data: dict[str, Any] = await request.json()

        # 更新字段
        for key, value in data.items():
            if key == "config":
                # 处理config字段的更新
                for config_key, config_value in value.items():
                    if hasattr(preset.config, config_key):
                        setattr(preset.config, config_key, config_value)
            elif key == "thinking_config":
                if value is None:
                    preset.thinking_config = None
                elif isinstance(value, dict):
                    if preset.thinking_config is None:
                        preset.thinking_config = ThinkingConfig()
                    for tc_key, tc_value in value.items():
                        if hasattr(preset.thinking_config, tc_key):
                            setattr(preset.thinking_config, tc_key, tc_value)
            elif key == "api_key":
                if value != KEY_PLACEHOLDER:
                    setattr(preset, key, value)
            elif hasattr(preset, key) and key != "name":  # 排除不可变的name字段
                setattr(preset, key, value)

        if name == "default":
            # default 预设即 config.default_preset（运行时模型配置），
            # 更新后写回配置并持久化（不能存到预设表文件，那里不生效）
            config_manager.config.default_preset = preset
            await config_manager.save_config()
        else:
            # 保存模型预设到文件
            preset_path = config_manager.get_preset_path(name)
            preset.save(preset_path)

        # 重新加载模型列表
        await config_manager.get_all_presets(cache=False)

        return JSONResponse(
            {"success": True, "message": f"模型预设 {name} 更新成功"}, status_code=200
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error(
            "[webui] 模型预设更新失败: %s", e
        )
        return JSONResponse(
            {"success": False, "message": f"更新模型预设失败: {e!s}"},
            status_code=500,
        )


@router.post("/api/chat/models/{name}/delete")
async def delete_model(name: str):
    try:
        # default 预设是运行时配置（config.default_preset），不可删除
        if name == "default":
            return JSONResponse(
                {"success": False, "message": "默认预设不可删除"},
                status_code=400,
            )

        preset_path = config_manager.get_preset_path(name)

        if not preset_path.exists():
            return JSONResponse(
                {"success": False, "message": f"模型预设 {name} 不存在"},
                status_code=404,
            )
        preset_path.unlink()

        # 重新加载模型列表
        await config_manager.get_all_presets(cache=False)
        config_manager.forget_preset(name)

        return JSONResponse(
            {"success": True, "message": f"模型预设 {name} 删除成功"}, status_code=200
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error(
            f"Error in delete preset {name}"
        )
        return JSONResponse(
            {"success": False, "message": f"删除模型预设失败: {e!s}"},
            status_code=500,
        )


@router.get("/api/chat/models")
async def get_models():
    try:
        models = copy.deepcopy(await config_manager.get_all_presets(cache=False))
        model_data = []
        for model in models:
            model.api_key = KEY_PLACEHOLDER
            model_data.append(model.model_dump())

        return JSONResponse(
            {"success": True, "data": {"models": model_data}}, status_code=200
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("获取模型预设列表失败")
        return JSONResponse(
            {"success": False, "message": f"获取模型预设列表失败: {e!s}"},
            status_code=500,
        )


@router.post("/api/chat/prompts/{prompt_type}")
async def create_prompt(request: Request, prompt_type: str):
    try:
        data: dict[str, Any] = await request.json()
        name = data.get("name")
        text = data.get("text", "")

        if not name:
            return JSONResponse(
                {"success": False, "message": "缺少提示词名称"}, status_code=400
            )

        if prompt_type not in ["group", "private"]:
            return JSONResponse(
                {"success": False, "message": "提示词类型必须是 'group' 或 'private'"},
                status_code=400,
            )

        # 确定保存路径
        prompt_dir = (
            config_manager.group_prompts
            if prompt_type == "group"
            else config_manager.private_prompts
        )
        prompt_path = prompt_dir / f"{name}.txt"

        # 检查是否已存在
        if prompt_path.exists():
            return JSONResponse(
                {"success": False, "message": f"{prompt_type}提示词 {name} 已存在"},
                status_code=400,
            )

        # 保存提示词到文件
        async with aiofiles.open(prompt_path, "w", encoding="utf-8") as f:
            await f.write(text)

        # 重新加载提示词列表
        await config_manager.get_prompts(cache=False)

        return JSONResponse(
            {"success": True, "message": f"{prompt_type}提示词 {name} 创建成功"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": f"创建提示词失败: {e!s}"}, status_code=500
        )


@router.post("/api/chat/prompts/{prompt_type}/{name}")
async def update_prompt(request: Request, prompt_type: str, name: str):
    try:
        data: dict[str, Any] = await request.json()
        text = data.get("text", "")

        if prompt_type not in ["group", "private"]:
            return JSONResponse(
                {"success": False, "message": "提示词类型必须是 'group' 或 'private'"},
                status_code=400,
            )

        # 确定保存路径
        prompt_dir = (
            config_manager.group_prompts
            if prompt_type == "group"
            else config_manager.private_prompts
        )
        prompt_path = prompt_dir / f"{name}.txt"

        # 检查是否存在
        if not prompt_path.exists():
            return JSONResponse(
                {"success": False, "message": f"{prompt_type}提示词 {name} 不存在"},
                status_code=404,
            )
        new_name = data.get("name", name)
        if name == "default" and new_name != "default":
            return JSONResponse(
                {"success": False, "message": "default提示词不允许改名"},
                status_code=400,
            )

        # 如果是当前提示词，需要更新配置
        update_config = False
        if (
            prompt_type == "group"
            and config_manager.config.group_prompt_character == name
        ):
            update_config = True
            config_manager.ins_config.group_prompt_character = new_name
        elif (
            prompt_type == "private"
            and config_manager.config.private_prompt_character == name
        ):
            update_config = True
            config_manager.ins_config.private_prompt_character = new_name

        # 如果改名了，需要删除旧文件并创建新文件
        if new_name != name:
            new_prompt_path = prompt_dir / f"{new_name}.txt"
            if new_prompt_path.exists():
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"{prompt_type}提示词 {new_name} 已存在",
                    },
                    status_code=400,
                )

            # 重命名文件
            prompt_path.rename(new_prompt_path)
            prompt_path = new_prompt_path

        # 更新提示词到文件
        async with aiofiles.open(prompt_path, "w", encoding="utf-8") as f:
            await f.write(text)

        # 如果更新了配置，需要保存配置
        if update_config:
            await config_manager.save_config()

        # 重新加载提示词列表
        await config_manager.get_prompts(cache=False)

        return JSONResponse(
            {"success": True, "message": f"{prompt_type}提示词 {name} 更新成功"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": f"更新提示词失败: {e!s}"}, status_code=500
        )


@router.post("/api/chat/prompts/{prompt_type}/{name}/delete")
async def delete_prompt(prompt_type: str, name: str):
    try:
        if prompt_type not in ["group", "private"]:
            return JSONResponse(
                {"success": False, "message": "提示词类型必须是 'group' 或 'private'"},
                status_code=400,
            )

        # 禁止删除default提示词
        if name == "default":
            return JSONResponse(
                {"success": False, "message": "不能删除default提示词"}, status_code=400
            )

        # 确定保存路径
        prompt_dir = (
            config_manager.group_prompts
            if prompt_type == "group"
            else config_manager.private_prompts
        )
        prompt_path = prompt_dir / f"{name}.txt"

        # 检查是否存在
        if not prompt_path.exists():
            return JSONResponse(
                {"success": False, "message": f"{prompt_type}提示词 {name} 不存在"},
                status_code=404,
            )

        # 删除文件
        prompt_path.unlink()

        # 重新加载提示词列表
        await config_manager.get_prompts(cache=False)

        return JSONResponse(
            {"success": True, "message": f"{prompt_type}提示词 {name} 删除成功"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": f"删除提示词失败: {e!s}"}, status_code=500
        )


@router.get("/api/chat/prompts")
async def get_prompts():
    try:
        # 重新加载提示词列表以确保最新
        await config_manager.get_prompts(cache=True)

        # 获取群组提示词列表
        group_prompts = [
            {"name": prompt.name, "text": prompt.text}
            for prompt in config_manager.prompts.group
        ]

        # 获取私聊提示词列表
        private_prompts = [
            {"name": prompt.name, "text": prompt.text}
            for prompt in config_manager.prompts.private
        ]

        return JSONResponse(
            {
                "success": True,
                "data": {
                    "prompts": {"group": group_prompts, "private": private_prompts}
                },
            },
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": f"获取提示词列表失败: {e!s}"},
            status_code=500,
        )


@router.get("/api/chat/mcp/servers")
async def get_mcp_servers():
    """获取MCP服务器列表"""
    try:
        client_manager = ClientManager()
        servers = []

        for client in client_manager.clients:
            client.get_tools()
            server_info = {
                "server_script": str(client.server_script),
                "tools_count": len(client.openai_tools),
                "status": "connected",
            }
            servers.append(server_info)

        # 获取配置中所有已定义的服务器脚本
        config_scripts = (
            config_manager.config.core.function_config.agent_mcp_server_scripts
        )
        for script in config_scripts:
            if script not in [s["server_script"] for s in servers]:
                servers.append(
                    {
                        "server_script": script,
                        "tools_count": 0,
                        "status": "disconnected",
                    }
                )

        return JSONResponse(
            {"success": True, "data": {"servers": servers}}, status_code=200
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("获取MCP服务器列表失败")
        return JSONResponse(
            {
                "success": False,
                "message": "获取MCP服务器列表失败，请检查服务器日志获取详细信息",
            },
            status_code=500,
        )


@router.post("/api/chat/mcp/servers")
async def add_mcp_server(request: Request):
    """添加MCP服务器"""
    try:
        data: dict[str, Any] = await request.json()
        server_script = data.get("server_script")

        if not server_script:
            return JSONResponse(
                {"success": False, "message": "缺少服务器脚本路径"}, status_code=400
            )

        config = config_manager.ins_config
        if server_script in config.core.function_config.agent_mcp_server_scripts:
            return JSONResponse(
                {"success": False, "message": "MCP服务器已存在"}, status_code=400
            )

        # 尝试初始化MCP服务器
        client_manager = ClientManager()
        await client_manager.initialize_this(server_script, True)

        # 保存到配置
        config.core.function_config.agent_mcp_server_scripts.append(server_script)
        await config_manager.save_config()

        return JSONResponse(
            {"success": True, "message": f"MCP服务器 {server_script} 添加成功"},
            status_code=200,
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("添加MCP服务器失败")
        return JSONResponse(
            {
                "success": False,
                "message": "添加MCP服务器失败，请检查服务器日志获取详细信息",
            },
            status_code=500,
        )


@router.put("/api/chat/mcp/servers/{server_script}")
async def update_mcp_server(server_script: str, request: Request):
    """更新MCP服务器（目标路径在 URL 中）"""
    try:
        data = await request.json()
        new_server_script = data.get("server_script")
        old_server_script = server_script

        if not new_server_script:
            return JSONResponse(
                {"success": False, "message": "缺少服务器脚本路径"}, status_code=400
            )

        config = config_manager.ins_config
        if (
            old_server_script
            not in config.core.function_config.agent_mcp_server_scripts
        ):
            return JSONResponse(
                {"success": False, "message": "MCP服务器不存在"}, status_code=404
            )

        # 从配置中移除旧服务器
        config.core.function_config.agent_mcp_server_scripts.remove(old_server_script)
        # 注销旧客户端
        client_manager = ClientManager()
        await client_manager.unregister_client(old_server_script)

        # 尝试初始化新MCP服务器
        await client_manager.initialize_this(new_server_script, True)

        # 添加新服务器到配置
        config.core.function_config.agent_mcp_server_scripts.append(new_server_script)
        await config_manager.save_config()

        return JSONResponse(
            {
                "success": True,
                "message": f"MCP服务器 {old_server_script} 已更新为 {new_server_script}",
            },
            status_code=200,
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("更新MCP服务器失败")
        return JSONResponse(
            {
                "success": False,
                "message": "更新MCP服务器失败，请检查服务器日志获取详细信息",
            },
            status_code=500,
        )


@router.post("/api/chat/mcp/servers/{server_script}/delete")
async def delete_mcp_server(server_script: str):
    """删除MCP服务器"""
    try:
        config = config_manager.ins_config
        if server_script not in config.core.function_config.agent_mcp_server_scripts:
            return JSONResponse(
                {"success": False, "message": "MCP服务器不存在"}, status_code=404
            )

        # 从配置中移除
        config.core.function_config.agent_mcp_server_scripts.remove(server_script)

        # 注销客户端
        client_manager = ClientManager()
        await client_manager.unregister_client(server_script)

        # 保存配置
        await config_manager.save_config()

        return JSONResponse(
            {"success": True, "message": f"MCP服务器 {server_script} 删除成功"},
            status_code=200,
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("删除MCP服务器失败")
        return JSONResponse(
            {"success": False, "message": "删除MCP服务器失败"},
            status_code=500,
        )


@router.post("/api/chat/mcp/servers/actions/reload")
async def reload_mcp_servers():
    """重载所有MCP服务器"""
    try:
        client_manager = ClientManager()
        for cl in (client_manager.clients).copy():
            await client_manager.unregister_client(cl.server_script)
            await cl.close_no_wait()  # 虽然热重载，但是为了避免竞态，这里先把会话掐了
            cl.tools.clear()
            cl.openai_tools.clear()
            await cl.bound_to(client_manager)

        return JSONResponse(
            {"success": True, "message": "MCP服务器重载成功"}, status_code=200
        )
    except Exception as e:
        logger.opt(exception=e, colors=True, raw=True).error("重载MCP服务器失败")
        return JSONResponse(
            {
                "success": False,
                "message": "重载MCP服务器失败，查看控制台以获得详细信息",
            },
            status_code=500,
        )


@router.get("/api/chat/insights")
async def get_chat_insights():
    """信息统计：Token 用量与历史图表数据。"""
    try:
        insight = await InsightsModel.get()
        insight_all = await InsightsModel.get_all()
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "token_prompt": insight.token_input,
                    "token_completion": insight.token_output,
                    "usage_count": insight.usage_count,
                    "chart_data": [
                        {
                            "date": i.date,
                            "token_input": i.token_input,
                            "token_output": i.token_output,
                            "usage_count": i.usage_count,
                        }
                        for i in insight_all
                    ],
                },
            },
            status_code=200,
        )
    except Exception as e:
        from nonebot import logger

        logger.opt(exception=e, colors=True, raw=True).error("获取信息统计失败")
        return JSONResponse(
            {"success": False, "message": "获取信息统计失败"},
            status_code=500,
        )
