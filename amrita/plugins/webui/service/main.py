from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import nonebot
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pytz import utc

from . import authlib
from .authlib import TOKEN_KEY, AuthManager, TokenManager
from .config import is_using_default_password
from .response import fail

STATIC_PATH = Path(__file__).resolve().parent / "static"

app: FastAPI = nonebot.get_app()
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


def try_get_bot():
    try:
        bot = nonebot.get_bot()
    except Exception:
        bot = None
    return bot


@app.exception_handler(Exception)
async def _(request: Request, exc: Exception):
    if not isinstance(exc, HTTPException):
        exc = HTTPException(500, repr(exc))
        nonebot.logger.opt(exception=exc, colors=True, raw=True).exception(
            "An Exception occurred in Amrita WebUI"
        )
    return await handle_http_exc(request, exc)


async def handle_http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        nonebot.logger.warning("401!" + str(request))
    return fail(exc.status_code, str(exc.detail))


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """认证中间件（白名单机制）。

    - 静态资源 / 公开端点 / 登录 API：放行
    - /api 端点：未认证返回 401 JSON（前端状态驱动显示登录页）
    - 页面路径：未认证 302 重定向到 /（即使前端被 patch，未登录也拿不到页面内容）
    - 已认证：续期 cookie（剩余 <10 分钟时刷新）
    """
    path = request.url.path

    # 公开路径白名单：静态资源、登录页本身、OneBot/文档端点
    public_paths = {
        "/",
        "/docs",
        "/onebot/v11",
        "/robots.txt",
        "/sitemap.xml",
    }
    if path.startswith("/static") or path in public_paths:
        return await call_next(request)

    # 安全锁：登录失败次数过多，UI 永久锁定（重启解除），所有访问拒绝
    if authlib.UI_SEC_LOCKED:
        if path.startswith("/api"):
            return JSONResponse(
                {
                    "code": 401,
                    "message": "登录失败次数过多，UI 已安全锁定，请重启 Amrita 解除",
                    "success": False,
                    "data": {"ui_sec_locked": True},
                },
                status_code=401,
            )
        return RedirectResponse(url="/", status_code=303)

    # 安全锁：仍在使用出厂默认密码时，拒绝所有访问（仅登录端点放行，登录时也会拒绝）
    if is_using_default_password():
        if path == "/api/auth/login":
            return await call_next(request)
        if path.startswith("/api"):
            return JSONResponse(
                {
                    "code": 423,
                    "message": "检测到默认密码，请在 .env 中设置 WEBUI_PASSWORD 后重启 Amrita",
                    "success": False,
                    "data": {"requires_password_change": True},
                },
                status_code=423,
            )
        # 页面路径：回到登录页（前端据此显示密码锁定提示）
        return RedirectResponse(url="/", status_code=303)

    try:
        await AuthManager().check_current_user(request)
    except HTTPException as e:
        if e.status_code != 401:
            raise
        if path.startswith("/api"):
            if path == "/api/auth/login":
                return await call_next(request)
            return JSONResponse(
                {"code": 401, "message": "未授权", "success": False, "data": None},
                status_code=401,
            )
        return RedirectResponse(url="/", status_code=303)

    # 已认证：剩余 <10 分钟时续期 cookie
    access_token = request.cookies.get(TOKEN_KEY)
    assert access_token
    response: Response = await call_next(request)
    if (
        token_data := await TokenManager().get_token_data(access_token, None)
    ) is not None:
        expire = token_data.expire
        if expire - datetime.now(utc) < timedelta(minutes=10):
            access_token = await AuthManager().refresh_token(request)
            response.set_cookie(
                key=TOKEN_KEY,
                value=access_token,
                httponly=True,
                samesite="lax",
            )
    return response


def register_spa_fallback():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return fail(404, "接口不存在")
        index_file = STATIC_PATH / "index.html"
        if not index_file.exists():
            return fail(503, "WebUI 尚未构建，请先在 frontend/ 目录执行构建")
        return FileResponse(index_file)


def mount_spa_fallback_on_startup():
    """在 NoneBot 启动时（所有插件加载完成后）注册 SPA catch-all。"""
    driver = nonebot.get_driver()

    @driver.on_startup
    async def _register_fallback():
        # 防止重复注册（热重载场景）
        from starlette.routing import Route

        paths = {
            r.path for r in app.routes if isinstance(r, Route) and hasattr(r, "path")
        }
        if "/{full_path:path}" in paths:
            return
        register_spa_fallback()
