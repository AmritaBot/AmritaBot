"""消息渲染与转义（chat 主流程与静默上下文存储共用）。

两种格式：

- XML：``<msg role="群主/管理员/普通成员" name="昵称" uid="QQ号" time="发送时间">内容</msg>``
- legacy：``[身份][时间][昵称（QQ号）]说:内容``

两者的 ``time`` 都是可选的：主流程与静默上下文记录都会传，
不传时输出与历史版本逐字节一致。
"""

from __future__ import annotations

__all__ = [
    "escape_content",
    "escape_xml",
    "escape_xml_attr",
    "format_msg_legacy",
    "format_msg_xml",
]


def escape_content(raw: str) -> str:
    """
    转义用户输入中可能与 legacy 消息格式冲突的字符。

    legacy 格式使用 [...] 标记用户身份、说: 标记发言，
    用户输入中出现相同字符时全角替换以避免 LLM 误解析。
    """
    return raw.replace("[", "\uff3b").replace("]", "\uff3d").replace("说:", "说：")


def escape_xml(raw: str) -> str:
    """
    转义用户输入中可能与 XML 消息格式冲突的字符。

    < > & 替换为 XML 实体，防止用户输入被当作标签解析。
    """
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_xml_attr(raw: str) -> str:
    """转义 XML 属性值：在 :func:`escape_xml` 基础上额外处理双引号。

    昵称等用户可控内容直接拼进属性时，未转义的 ``"`` 会提前闭合属性
    并注入伪造属性。
    """
    return escape_xml(raw).replace('"', "&quot;")


def format_msg_legacy(
    role: str, name: str, uid: str, content: str, time: str | None = None
) -> str:
    """legacy 格式：方括号标记，紧凑风格

    ``time`` 非空时渲染为 ``[身份][时间][昵称（QQ号）]说:内容``。
    """
    safe_content = escape_content(content)
    safe_name = escape_content(name)
    stamp = f"[{time}]" if time else ""
    if role:
        return f"[{role}]{stamp}[{safe_name}（{uid}）]说:{safe_content}"
    return f"{stamp}[{safe_name}（{uid}）]说:{safe_content}"


def format_msg_xml(
    role: str,
    name: str,
    uid: str,
    content: str,
    time: str | None = None,
    *,
    content_escaped: bool = False,
) -> str:
    """XML 格式：标签标记，结构清晰，天然支持多行

    ``time`` 非空时渲染为 ``time`` 属性，例如
    ``time="2026-09-19 Saturday 15:24:37"``（见 ``format_current_datetime``）。
    ``content_escaped=True`` 用于内容已由调用方转义的场景（如已含 ``<ref>``
    块的引用消息），避免二次转义。
    """
    safe_content = content if content_escaped else escape_xml(content)
    safe_name = escape_xml_attr(name)
    attrs = f' role="{role}"' if role else ""
    extra = f' time="{escape_xml_attr(time)}"' if time else ""
    return (
        f'<msg{attrs} name="{safe_name}" uid="{escape_xml_attr(uid)}"{extra}>\n'
        f"{safe_content}\n</msg>"
    )
