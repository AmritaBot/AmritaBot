"""认证 API：登录 / 登出 / 当前用户。

复用 authlib 现有机制（httpOnly Cookie + TokenManager + 登录限流），
仅将交互方式从 HTML Form 改为 JSON。
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, Request
from pydantic import BaseModel

from ..authlib import TOKEN_KEY, AuthManager, TokenManager
from ..config import is_using_default_password
from ..main import app
from ..response import fail, ok


class LoginSchema(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(request: Request, data: LoginSchema):
    """登录：校验凭据并设置 httpOnly Cookie。"""
    # 安全锁：默认密码不可用于登录，强制要求更换后再使用
    if is_using_default_password():
        return fail(
            423,
            "检测到默认密码，请在 .env 中设置 WEBUI_PASSWORD 后重启 Amrita",
            status_code=423,
        )
    if not await AuthManager().authenticate_user(request, data.username, data.password):
        return fail(401, "用户名或密码错误")
    access_token_expires = timedelta(minutes=30)
    access_token = await AuthManager().create_token(data.username, access_token_expires)
    response = ok("登录成功", data={"username": data.username})
    response.set_cookie(
        key=TOKEN_KEY,
        value=access_token,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/api/auth/logout")
async def logout(request: Request):
    """登出：吊销 token 并清除 Cookie。"""
    if token := request.cookies.get(TOKEN_KEY):
        await AuthManager().user_log_out(token)
    response = ok("已登出")
    response.delete_cookie(TOKEN_KEY)
    return response


@app.get("/api/auth/me")
async def me(request: Request):
    """当前登录用户信息。"""
    access_token = request.cookies.get(TOKEN_KEY)
    if not access_token:
        raise HTTPException(status_code=401, detail="未授权")
    token_data = await TokenManager().get_token_data(access_token, None)
    if token_data is None:
        raise HTTPException(status_code=401, detail="未授权")
    return ok("success", data={"username": token_data.username})
