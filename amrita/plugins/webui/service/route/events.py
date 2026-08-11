"""事件查看器 API —— 基于 event.json 的追溯数据。"""

from __future__ import annotations

from fastapi import Request

from amrita.utils.logging import LoggingData

from ..main import app
from ..response import fail, ok


@app.get("/api/events")
async def list_events(request: Request):
    """事件列表（基于 event.json 追溯数据，按时间倒序）。

    查询参数：
    - level: 按级别过滤（INFO/DEBUG/WARNING/ERROR/FATAL，可逗号分隔多个）
    - keyword: 按描述关键词过滤
    - limit: 返回条数上限（默认 500，倒序取最新）
    """
    try:
        params = request.query_params
        levels = [
            l.strip().upper() for l in params.get("level", "").split(",") if l.strip()
        ]
        keyword = params.get("keyword", "").strip().lower()
        try:
            limit = int(params.get("limit", "500"))
        except ValueError:
            limit = 500

        data = await LoggingData.get()
        events = data.data

        if levels:
            events = [e for e in events if e.log_level in levels]
        if keyword:
            events = [
                e
                for e in events
                if keyword in e.description.lower()
                or keyword in (e.message or "").lower()
            ]

        # 倒序：最新在前
        events = events[-limit:][::-1] if limit > 0 else events[::-1]

        return ok(
            "success",
            data={
                "total": len(events),
                "events": [
                    {
                        "time": e.time.strftime("%Y-%m-%d %H:%M:%S"),
                        "level": e.log_level,
                        "desc": e.description,
                        "message": e.message,
                        "traceback": e.traceback,
                        "icon_color": e.color,
                        "icon": e.icon,
                    }
                    for e in events
                ],
            },
        )
    except Exception:
        return fail(500, "读取事件数据失败")
