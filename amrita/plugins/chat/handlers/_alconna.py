"""chat 管理命令共用的 Alconna 参数提取辅助。"""

from __future__ import annotations

from nonebot_plugin_alconna import CommandResult


def extract_raw_args(result: CommandResult) -> str:
    """从 ``Alconna(cmd, Args["args?", AllParam])`` 的结果中提取纯文本参数串。"""
    raw = result.result.main_args.get("args")
    if raw is None:
        return ""
    if hasattr(raw, "extract_plain_text"):
        return str(raw.extract_plain_text())
    return str(raw)
