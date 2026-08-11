from __future__ import annotations

import glob
import logging
import os
from pathlib import Path

import aiofiles
from fastapi import Request

from amrita.plugins.webui.service.response import fail, ok

from ..main import app

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(os.getcwd())


def _list_env_files() -> list[str]:
    env_files = glob.glob(str(PROJECT_ROOT / ".env*"))
    return [Path(f).name for f in env_files if not f.endswith((".py", ".pyc", ".pyo"))]


@app.get("/api/bot/config")
async def list_config_files():
    """配置文件列表。"""
    files = _list_env_files()
    selected = ".env" if ".env" in files else (files[0] if files else None)
    content = ""
    if selected:
        env_file_path = PROJECT_ROOT / selected
        if env_file_path.exists():
            async with aiofiles.open(env_file_path, encoding="utf-8") as f:
                content = await f.read()
    return ok(
        "success",
        data={"files": files, "selected": selected, "content": content},
    )


@app.post("/api/bot/config")
async def update_config(request: Request):
    """保存配置文件内容。"""
    data = await request.json()
    content = data.get("content", "")
    filename = data.get("filename", ".env")

    if not filename or filename.startswith((".", "/")):
        return fail(400, "非法的文件名")
    if filename not in _list_env_files():
        return fail(404, f"文件 {filename} 不存在")

    try:
        env_file_path = PROJECT_ROOT / filename
        async with aiofiles.open(env_file_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return ok(f"配置文件 {filename} 更新成功")
    except Exception:
        logger.exception("Failed to update config file")
        return fail(500, "配置文件更新失败")


@app.get("/api/bot/config/{filename}")
async def get_config(filename: str):
    """获取指定配置文件内容。"""
    try:
        env_file_path = PROJECT_ROOT / filename
        if not env_file_path.exists():
            return fail(404, "文件不存在", data={"content": ""})

        async with aiofiles.open(env_file_path, encoding="utf-8") as f:
            content = await f.read()
        return ok("success", data={"content": content})
    except Exception:
        logger.exception("Failed to read config file")
        return fail(500, "读取文件失败")
