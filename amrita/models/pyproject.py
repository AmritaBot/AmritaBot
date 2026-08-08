"""Pyproject.toml Pydantic 模型

从 amrita.cmds.main 提取而来，供运行时 `amrita.utils.plugins` 读取项目配置使用。
"""

from typing import Any

from pydantic import BaseModel, Field

from ..utils.utils import get_amrita_version


class Pyproject(BaseModel):
    """Pyproject.toml 项目配置模型"""

    name: str
    description: str = ""
    version: str = "0.1.0"
    dependencies: list[str] = Field(
        default_factory=lambda: [f"amrita[full]>={get_amrita_version()}"]
    )
    readme: str = "README.md"
    requires_python: str = Field(default=">=3.10, <3.14", alias="requires-python")


class NonebotTool(BaseModel):
    """Nonebot 工具配置模型"""

    plugins: list[str] = [
        "nonebot_plugin_orm",
    ]
    adapters: list[dict[str, Any]] = [
        {"name": "OneBot V11", "module_name": "nonebot.adapters.onebot.v11"},
    ]
    plugin_dirs: list[str] = []


class RUFFLint(BaseModel):
    """Ruff lint 工具配置模型"""

    select: list[str] = [
        "F",
        "W",
        "E",
        "UP",
        "ASYNC",
        "C4",
        "T10",
        "PYI",
        "PT",
        "Q",
        "RUF",
        "I",
        "PERF",
    ]
    ignore: list[str] = [
        "E402",
        "E501",
        "UP037",
        "RUF001",
        "RUF002",
        "RUF003",
    ]


class RUFFTool(BaseModel):
    """Ruff 工具配置模型"""

    line_length: int = Field(default=88, alias="line-length")
    target_version: str = Field(default="py310", alias="target-version")
    lint: RUFFLint = RUFFLint()


class SetupToolPackagesFinder(BaseModel):
    """Setup 工具包查找配置"""

    exclude: list[str] = Field(default_factory=lambda: ["__pycache__", "*.pyc"])
    include: list[str] = Field(default_factory=lambda: ["plugins", "src/plugins"])


class SetupToolPackages(BaseModel):
    """Setup 工具包配置"""

    find: SetupToolPackagesFinder = SetupToolPackagesFinder()


class SetupTool(BaseModel):
    """Setup 工具配置模型"""

    packages: SetupToolPackages = SetupToolPackages()

class AmritaTool(BaseModel):
    """Amrita 工具配置模型"""

    plugins: list[str] = [
        "amrita.plugins.chat",
        "amrita.plugins.manager",
        "amrita.plugins.menu",
        "amrita.plugins.perm",
    ]


class Tool(BaseModel):
    """工具配置模型"""

    nonebot: NonebotTool = NonebotTool()
    amrita: AmritaTool = AmritaTool()
    ruff: RUFFTool = RUFFTool()
    pyright: dict[str, Any] = Field(
        default_factory=lambda: {"typeCheckingMode": "standard"}
    )
    setuptools: SetupTool = SetupTool()


class PyprojectFile(BaseModel):
    """Pyproject 文件模型"""

    project: Pyproject = Pyproject(name="amrita")
    tool: Tool = Tool()
