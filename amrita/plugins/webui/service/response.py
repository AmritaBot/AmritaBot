"""WebUI 统一 API 响应格式

所有 API 端点统一返回:
    {"code": int, "message": str, "success": bool, "data": Any | None}

用法:
    from amrita.plugins.webui.service.response import ok, fail

    return ok("操作成功", data={...})
    return fail(400, "参数错误")
    return fail(500, "内部错误", exc=e)
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class APIResponse:
    """统一 API 响应包装器。

    不直接实例化，使用 ok() / fail() 工厂函数。
    """

    @staticmethod
    def ok(message: str = "ok", data: Any = None) -> JSONResponse:
        return JSONResponse(
            {
                "code": 200,
                "message": message,
                "success": True,
                "data": data,
            },
            status_code=200,
        )

    @staticmethod
    def fail(
        code: int,
        message: str = "error",
        data: Any = None,
        *,
        status_code: int | None = None,
    ) -> JSONResponse:
        """status_code 默认跟随 code（4xx/5xx 业务码通常即 HTTP 码）。"""
        if status_code is None:
            status_code = code
        return JSONResponse(
            {
                "code": code,
                "message": message,
                "success": False,
                "data": data,
            },
            status_code=status_code,
        )


ok = APIResponse.ok
fail = APIResponse.fail
