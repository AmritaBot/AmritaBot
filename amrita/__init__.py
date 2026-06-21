"""Amrita框架初始化模块

该模块是Amrita框架的入口点，负责导入和初始化核心组件。
对外暴露两个透传API函数，供外部CLI工具（如 amctl）调用。
"""

import nonebot
from nonebot import run

from .config import get_amrita_config
from .utils.bot_utils import init
from .utils.plugins import load_plugins
from .utils.utils import get_amrita_version


def prepare_nb_cli():
    """加载 Amrita 框架，返回 nb-cli 原生 CLI 入口函数。

    调用 init() 和 load_plugins() 完成框架初始化后，
    返回 nb_cli.__main__.main 的函数引用，
    供外部 CLI 工具透传调用。

    Returns:
        nb_cli.__main__.main 函数，签名: main(argv: list[str]) -> None
    """
    init()
    load_plugins()
    from nb_cli.__main__ import main as nb_main

    return nb_main


def prepare_orm():
    """加载 Amrita 框架，返回 nonebot-plugin-orm CLI 入口函数。

    调用 init() 和 load_plugins() 完成框架初始化，
    并通过 nonebot.require 加载 ORM 插件后，
    返回 nonebot_plugin_orm.__main__.main 的函数引用。

    Returns:
        nonebot_plugin_orm.__main__.main 函数，签名: main(argv: list[str]) -> None
    """
    init()
    load_plugins()
    nonebot.require("nonebot_plugin_orm")
    from nonebot_plugin_orm.__main__ import main as orm_main

    return orm_main


__all__ = [
    "get_amrita_config",
    "get_amrita_version",
    "init",
    "load_plugins",
    "nonebot",
    "prepare_nb_cli",
    "prepare_orm",
    "run",
]
