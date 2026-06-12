"""Amrita CLI工具模块

该模块提供了Amrita项目的命令行界面工具，用于项目管理、依赖检查、插件管理等功能。
"""

import contextlib
import os
import signal
import subprocess
import sys
from logging import warning
from typing import Any

import click
import colorama
import requests
from colorama import Fore, Style
from packaging import version

from amrita.utils.dependencies import self_check_optional_dependency
from amrita.utils.utils import get_amrita_version

# 全局变量用于跟踪子进程
_subprocesses: list[subprocess.Popen] = []


def get_package_metadata(package_name: str) -> dict[str, Any] | None:
    """获取PyPI包的元数据信息

    Args:
        package_name: 包名称

    Returns:
        包的元数据字典，如果获取失败则返回None
    """
    try:
        response = requests.get(
            f"https://pypi.org/pypi/{package_name}/json", timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return


def should_update() -> tuple[bool, str]:
    if metadata := get_package_metadata("amrita"):
        if metadata["releases"] and version.parse(
            max(list(metadata["releases"].keys()), key=version.parse)
        ) > version.parse(get_amrita_version()):
            latest_version = list(metadata["releases"].keys())[-1]
            return True, latest_version
        else:
            click.echo(
                success(
                    "主环境Amrita已是最新版本。"
                    if not IS_IN_VENV
                    else "虚拟环境Amrita已是最新版本。"
                )
            )
    return False, get_amrita_version()


def run_proc(
    cmd: list[str], stdin=None, stdout=sys.stdout, stderr=sys.stderr, **kwargs
):
    """运行子进程并等待其完成

    Args:
        cmd: 要执行的命令列表
        stdin: 标准输入流
        stdout: 标准输出流
        stderr: 标准错误流
        **kwargs: 其他传递给Popen的参数

    Returns:
        进程的返回码

    Raises:
        subprocess.CalledProcessError: 当进程返回非零退出码时
    """
    proc = subprocess.Popen(
        cmd,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        **kwargs,
    )
    _subprocesses.append(proc)
    try:
        return_code = proc.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(
                return_code, cmd, output=proc.stderr.read() if proc.stderr else None
            )
    except KeyboardInterrupt:
        _cleanup_subprocesses()
        sys.exit(0)
    finally:
        # 使用copy()避免在多线程环境中列表被修改
        if proc in _subprocesses.copy():
            _subprocesses.remove(proc)


def stdout_run_proc(cmd: list[str]):
    """运行子进程并返回标准输出

    Args:
        cmd: 要执行的命令列表

    Returns:
        进程的标准输出内容（字符串格式）

    Raises:
        subprocess.CalledProcessError: 当进程返回非零退出码时
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _ = proc.communicate()
    _subprocesses.append(proc)
    try:
        return_code = proc.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, cmd)
    except KeyboardInterrupt:
        _cleanup_subprocesses()
        sys.exit(0)
    finally:
        # 使用copy()避免在多线程环境中列表被修改
        if proc in _subprocesses.copy():
            _subprocesses.remove(proc)
    return stdout.decode("utf-8")


__is_cleaning = False


def _cleanup_subprocesses():
    """清理所有子进程

    终止所有正在运行的子进程
    """
    global __is_cleaning
    if __is_cleaning:
        return  # 避免重复清理
    __is_cleaning = True

    procs_to_cleanup = _subprocesses.copy()
    for proc in procs_to_cleanup:
        with contextlib.suppress(Exception):
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    _subprocesses.clear()


def _signal_handler(signum, frame):
    """信号处理函数

    当接收到终止信号时，清理所有子进程并退出程序。

    Args:
        signum: 信号编号
        frame: 当前堆栈帧
    """
    global __is_cleaning
    if __is_cleaning:
        # 如果已经在清理过程中，直接退出
        import os

        os._exit(0)
    click.echo(warn("正在清理进程..."))
    _cleanup_subprocesses()


# 注册信号处理函数
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def check_optional_dependency(
    with_details: bool = False, quiet: bool = False
) -> bool | tuple[bool, list[str]]:
    """检测amrita[full]可选依赖是否已安装

    Args:
        is_self: 是否在当前环境中直接检查
        with_details: 是否返回详细信息（缺失的依赖列表）

    Returns:
        如果with_details为True，返回(状态, 缺失依赖列表)元组；
        否则只返回状态布尔值
    """
    if not IS_IN_VENV:
        try:
            run_proc(
                ["uv", "run", "amrita", "check-dependencies"],
                stdout=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError:
            return False
    else:
        status, missed = self_check_optional_dependency()
        if not status and not quiet:
            click.echo(error("一些可选依赖已丢失，但是您可以重新安装它们。"))
            for pkg in missed:
                click.echo(f"- {pkg} 是被要求的，但是没有被找到。")
            click.echo(info("您可以通过以下方式来安装它们:\n  uv add amrita[full]"))
        if with_details:
            return status, missed
        return status


def install_optional_dependency_no_venv() -> bool:
    """在不使用虚拟环境的情况下安装可选依赖

    Returns:
        安装是否成功
    """
    try:
        run_proc(["pip", "install", "amrita[full]"])
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo(error("pip 运行失败。"))
        return False


def install_optional_dependency() -> bool:
    """安装amrita[full]可选依赖

    使用uv工具安装amrita的完整依赖包。

    Returns:
        安装是否成功
    """
    try:
        proc = subprocess.Popen(
            ["uv", "add", "amrita[full]"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        _subprocesses.append(proc)
        try:
            return_code = proc.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code, ["uv", "add", "amrita[full]"]
                )
            return True
        except KeyboardInterrupt:
            _cleanup_subprocesses()
            sys.exit(0)
        finally:
            if proc in _subprocesses:
                _subprocesses.remove(proc)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        click.echo(
            error(
                f"因为`{e}`，我们无法自动安装可选依赖, 尝试通过此方式手动安装： 'uv add amrita[full]'"
            )
        )
        return False


def check_nb_cli_available():
    """检查nb-cli是否可用

    Returns:
        nb-cli是否可用
    """
    try:
        proc = subprocess.Popen(
            ["nb", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        _subprocesses.append(proc)
        try:
            proc.communicate(timeout=10)
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            return False
        finally:
            if proc in _subprocesses:
                _subprocesses.remove(proc)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def warn(message: str):
    """返回带警告颜色的消息

    Args:
        message: 要着色的消息文本

    Returns:
        带颜色编码的警告消息
    """
    return f"{Fore.YELLOW}[!]{Style.RESET_ALL} {message}"


def info(message: str):
    """返回带信息颜色的消息

    Args:
        message: 要着色的消息文本

    Returns:
        带颜色编码的信息消息
    """
    return f"{Fore.GREEN}[+]{Style.RESET_ALL} {message}"


def error(message: str):
    """返回带错误颜色的消息

    Args:
        message: 要着色的消息文本

    Returns:
        带颜色编码的错误消息
    """
    return f"{Fore.RED}[-]{Style.RESET_ALL} {message}"


def question(message: str):
    """返回带问题颜色的消息

    Args:
        message: 要着色的消息文本

    Returns:
        带颜色编码的问题消息
    """
    return f"{Fore.BLUE}[?]{Style.RESET_ALL} {message}"


def success(message: str):
    """返回带成功颜色的消息

    Args:
        message: 要着色的消息文本

    Returns:
        带颜色编码的成功消息
    """
    return f"{Fore.GREEN}[+]{Style.RESET_ALL} {message}"


def is_in_venv(fail_then_throw: bool = False) -> bool:
    """综合检查虚拟环境"""
    if (
        "AMRITA_IGNORE_VENV" in os.environ
        and os.environ["AMRITA_IGNORE_VENV"].lower() == "true"
    ):
        click.echo(
            warning("虚拟环境检查已被禁用。这通常不是推荐做法，但如您所愿，这将继续。")
        )
        return True

    methods = {
        "VIRTUAL_ENV" in os.environ,
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix,
        hasattr(sys, "real_prefix"),
    }

    in_venv = any(methods)
    if in_venv:
        if "VIRTUAL_ENV" in os.environ:
            click.echo(info(f"使用虚拟环境路径: {os.environ['VIRTUAL_ENV']}"))
    elif fail_then_throw:
        raise Exception("未在虚拟环境中运行")
    return in_venv


IS_IN_VENV = is_in_venv()


@click.group()
def cli(*args, **kwargs):
    """Amrita CLI - PROJ.AmritaBot项目命令行工具"""


@cli.group()
def plugin():
    """管理插件。"""
    pass


cli.add_command(plugin)


def main(*args, **kwargs):
    colorama.init()
    click.echo(
        warn(
            "This CLI is deprecated. Please use `amctl` instead. We will remove this CLI in the future."
        )
    )

    cli(*args, **kwargs)
