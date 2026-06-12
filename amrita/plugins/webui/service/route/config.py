from __future__ import annotations

import glob
import os
from pathlib import Path

import aiofiles
from fastapi import Request
from fastapi.responses import HTMLResponse

from amrita.plugins.webui.service.response import fail, ok

from ..main import TemplatesManager, app
from ..sidebar import SideBarManager

# 获取项目根目录
PROJECT_ROOT = Path(os.getcwd())


@app.get("/bot/config", response_class=HTMLResponse)
async def config_editor(request: Request):
    """
    配置文件编辑器页面
    """
    # 获取所有.env文件
    env_files = glob.glob(str(PROJECT_ROOT / ".env*"))
    env_files = [
        Path(f).name for f in env_files if not f.endswith((".py", ".pyc", ".pyo"))
    ]

    # 默认选择.env文件
    selected_file = ".env"

    # 读取默认.env文件内容
    env_content = ""
    env_file_path = PROJECT_ROOT / selected_file
    if env_file_path.exists():
        async with aiofiles.open(env_file_path, encoding="utf-8") as f:
            env_content = await f.read()

    # 获取侧边栏
    side_bar = SideBarManager().get_sidebar_dump()
    for bar in side_bar:
        if bar.get("name") == "机器人管理":
            bar["active"] = True
            for child in bar.get("children", []):
                if child.get("name") == "配置管理":
                    child["active"] = True
                    break
            break

    return TemplatesManager().TemplateResponse(
        request,
        "config.html",
        {
            "sidebar_items": side_bar,
            "env_content": env_content,
            "env_files": env_files,
            "selected_file": selected_file,
        },
    )


@app.post("/api/bot/config")
async def update_config(request: Request):
    """
    更新配置文件API
    """

    # 获取请求数据
    data = await request.json()
    content = data.get("content", "")
    filename = data.get("filename", ".env")

    if not content:
        return fail(400, "Invalid request data")

    try:
        # 写入指定文件
        env_file_path = PROJECT_ROOT / filename
        async with aiofiles.open(env_file_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return ok(f"配置文件 {filename} 更新成功")
    except Exception as e:
        return fail(500, "配置文件更新失败", data=str(e))


@app.get("/api/bot/config/{filename}")
async def get_config(filename: str):
    """
    获取指定配置文件内容
    """
    try:
        # 读取指定文件
        env_file_path = PROJECT_ROOT / filename
        if not env_file_path.exists():
            return fail(404, "文件不存在", data={"content": ""})

        async with aiofiles.open(env_file_path, encoding="utf-8") as f:
            content = await f.read()
        return ok("success", data={"content": content})
    except Exception as e:
        return fail(500, "读取文件失败", data=str(e))
