from __future__ import annotations

import hashlib
import json
import logging
from ast import literal_eval
from typing import Any, Literal, get_args, get_origin

from fastapi import HTTPException, Request
from pydantic import BaseModel

from amrita.config_manager import UniConfigManager
from amrita.plugins.webui.API import PageContext, PageResponse, on_page
from amrita.plugins.webui.service.response import fail, ok
from amrita.plugins.webui.service.sidebar import SideBarCategory, SideBarManager

logger = logging.getLogger(__name__)


def flatten_config_fields(
    config_dict: dict, parent_key: str = "", sep: str = "."
) -> dict:
    """
    将嵌套的配置字典递归展平为一级字典
    例如: {'a': {'b': 1}} -> {'a.b': 1}
    """
    items = []
    for key, value in config_dict.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            # 递归处理嵌套字典
            items.extend(flatten_config_fields(value, new_key, sep).items())
        else:
            items.append((new_key, value))
    return dict(items)


def get_field_info(
    model: type[BaseModel], field_path: str, sep: str = "."
) -> tuple[str, Any, Any]:
    """
    根据字段路径获取Pydantic模型字段的描述信息、默认值和类型信息
    例如: 对于路径 "autoreply.enable"，会递归查找autoreply字段，然后查找enable字段的描述和默认值
    返回元组：(描述信息, 默认值, 字段类型)
    """
    field_parts = field_path.split(sep)
    current_model = model
    current_field_info = None

    try:
        for i, part in enumerate(field_parts):
            # 获取当前模型的字段信息
            if not hasattr(current_model, "model_fields"):
                return "", None, None

            model_fields = current_model.model_fields

            # 检查字段是否存在
            if part not in model_fields:
                return "", None, None

            current_field_info = model_fields[part]

            # 如果不是最后一个字段且字段类型是Pydantic模型，则继续深入
            if i < len(field_parts) - 1:
                field_annotation = current_field_info.annotation
                if hasattr(field_annotation, "__origin__"):  # 处理typing.Generic类型
                    # 简化处理，跳过复杂泛型类型
                    description = (
                        current_field_info.description
                        if current_field_info.description
                        else ""
                    )
                    default = (
                        current_field_info.default
                        if current_field_info.default
                        else None
                    )
                    return description, default, field_annotation

                if isinstance(field_annotation, type) and issubclass(
                    field_annotation, BaseModel
                ):
                    current_model = field_annotation
                else:
                    # 如果不是Pydantic模型，无法继续深入
                    description = (
                        current_field_info.description
                        if current_field_info.description
                        else ""
                    )
                    default = (
                        current_field_info.default
                        if current_field_info.default
                        else None
                    )
                    return description, default, field_annotation

        # 返回最终字段的描述、默认值和类型
        description = (
            current_field_info.description
            if current_field_info and current_field_info.description
            else ""
        )
        default = (
            current_field_info.default
            if current_field_info and current_field_info.default
            else None
        )
        annotation = (
            current_field_info.annotation
            if current_field_info and current_field_info.annotation
            else None
        )
        return description, default, annotation
    except Exception:
        # 出现任何异常都返回空描述和None默认值
        return "", None, None


def extract_literal_values(annotation):
    """
    提取 Literal 类型的值列表
    """
    origin = get_origin(annotation)
    if origin is Literal:
        args = get_args(annotation)
        return list(args)
    return None


def try_parse_value(value_str: Any) -> Any:
    """
    尝试解析字符串值为适当的Python类型。
    本函数旨在尽可能地进行无害转换，所有解析失败的情况都返回原始字符串，
    最终的类型验证由 Pydantic 的 model_validate 负责。
    """
    if not isinstance(value_str, str):
        return value_str

    # 去除首尾空白
    value_str = value_str.strip()

    # 如果字符串为空，则返回空字符串
    if not value_str:
        return ""

    # 尝试解析为Python字面量（包括列表、字典、布尔值、数字等）
    try:
        return literal_eval(value_str)
    except (ValueError, SyntaxError):
        # 解析失败，返回原始字符串，让后续的 model_validate 处理
        return value_str


def unflatten_config_fields(flat_dict: dict, sep: str = ".") -> dict:
    """
    将展平的配置字典还原为嵌套字典
    例如: {'a.b': 1} -> {'a': {'b': 1}}
    """
    result = {}
    for key, value in flat_dict.items():
        keys = key.split(sep)
        d = result
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]

        # 解析值的类型
        if isinstance(value, str):
            parsed_value = try_parse_value(value)
        else:
            parsed_value = value

        d[keys[-1]] = parsed_value
    return result


def deep_merge(base: dict, overlay: dict) -> dict:
    """
    深度合并两个嵌套字典。overlay 中的值覆盖 base，嵌套字典递归合并。
    """
    merged = dict(base)
    for key, val in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


SideBarManager().add_sidebar_category(
    SideBarCategory(name="系统管理", icon="fa fa-cog")
)


@on_page(
    path="/system/confedit",
    page_name="配置管理",
    category="系统管理",
)
async def system_config_list(ctx: PageContext):
    """
    系统配置列表页面 - 显示所有可配置的插件
    """
    # 获取所有已注册的配置类
    config_manager = UniConfigManager()
    config_classes = config_manager.get_config_classes()

    # 准备插件列表信息
    config_list = {}

    for plugin_name, config_class in config_classes.items():
        config_list[plugin_name] = {
            "class_name": config_class.__name__,
        }

    return PageResponse(
        name="system_confedit.html",
        context={"request": ctx.request, "config_list": config_list},
    )


@on_page(
    path="/system/confedit/{owner_name}",
    page_name="",
    category="__HIDDEN__",
)
async def system_config_editor(ctx: PageContext):
    """
    单个插件配置文件编辑页面
    从配置类的Field读取description作为字段描述信息
    """
    owner_name = ctx.request.path_params.get("owner_name")

    if not owner_name:
        raise HTTPException(404, detail="插件不存在")

    # 获取所有已注册的配置类
    config_manager = UniConfigManager()

    # 检查插件是否存在
    if not config_manager.has_config_class(owner_name):
        return PageResponse(
            name="error.html",
            context={
                "request": ctx.request,
                "error_message": f"插件 {owner_name} 未注册配置类",
            },
        )

    config_class = config_manager.get_config_class_by_name(owner_name)

    if config_class is None:
        return PageResponse(
            name="error.html",
            context={
                "request": ctx.request,
                "error_message": f"插件 {owner_name} 配置类不存在",
            },
        )

    # 获取当前配置实例
    if config_manager.has_config_instance(owner_name):
        config_instance = config_manager.get_config_instance_not_none(owner_name)
        config_data = config_instance.model_dump()
    else:
        # 如果还没有配置实例，则创建默认实例
        config_instance = config_class()
        config_data = config_instance.model_dump()

    # 展平配置数据
    flat_config_data = flatten_config_fields(config_data)

    # 获取模型字段信息
    fields_info = []
    for flat_key, flat_value in flat_config_data.items():
        # 获取字段描述信息、默认值和类型
        description, default_value, field_type = get_field_info(config_class, flat_key)
        if default_value is not None:
            dv_str = str(default_value)
            default_value = dv_str if len(dv_str) <= 20 else dv_str[:20] + "..."

        # 获取字段类型名
        type_name = type(flat_value).__name__

        # 检查是否为 Literal 类型
        literal_values = extract_literal_values(field_type) if field_type else None

        # 如果是 Literal 类型，更新类型名为 literal
        if literal_values:
            type_name = "literal"

        fields_info.append(
            {
                "name": flat_key,
                "description": description,
                "type": type_name,
                "literal_values": literal_values,  # 添加 Literal 值列表
                "default": default_value,
                "current_value": flat_value,
            }
        )

    plugin_info = {
        "class_name": config_class.__name__,
        "fields": fields_info,
    }

    # 计算配置哈希
    config_hash = calculate_config_hash(flat_config_data)

    return PageResponse(
        name="confedit_edit.html",
        context={
            "request": ctx.request,
            "plugin_name": owner_name,
            "plugin_info": plugin_info,
            "config_hash": config_hash,
        },
    )


async def get_plugin_config_data(plugin_name: str) -> dict[str, Any]:
    """
    获取插件当前配置数据
    """
    config_manager = UniConfigManager()

    # 获取当前配置实例
    if config_manager.has_config_instance(plugin_name):
        config_instance = config_manager.get_config_instance_not_none(plugin_name)
        config_data = config_instance.model_dump()
    else:
        # 如果还没有配置实例，则加载
        config_instance = await config_manager.get_config(plugin_name)
        config_data = config_instance.model_dump()

    # 展平嵌套配置
    flat_config_data = flatten_config_fields(config_data)
    return flat_config_data


def calculate_config_hash(config_data: dict[str, Any]) -> str:
    """
    计算配置数据的哈希值
    """
    # 将配置数据转换为排序后的JSON字符串，确保一致性
    config_str = json.dumps(config_data, sort_keys=True, separators=(",", ":"))
    # 计算SHA256哈希
    return hashlib.sha256(config_str.encode("utf-8")).hexdigest()


from ..main import app


@app.get("/api/confedit/{owner_name}")
async def get_plugin_config(owner_name: str):
    """
    获取指定插件的配置数据和哈希值
    """
    try:
        # 获取插件配置数据
        config_data = await get_plugin_config_data(owner_name)

        # 计算配置哈希
        config_hash = calculate_config_hash(config_data)

        return ok("success", data={"config": config_data, "hash": config_hash})
    except Exception:
        logger.exception("Failed to get plugin config")
        return fail(500, "获取配置失败")


@app.post("/api/confedit/{owner_name}")
async def save_plugin_config(owner_name: str, request: Request):
    """
    保存指定插件的配置数据
    """
    try:
        # 解析请求数据
        request_data = await request.json()
        new_config_data = request_data.get("config", {})
        provided_hash = request_data.get("hash", "")

        # 还原嵌套配置结构
        nested_config_data = unflatten_config_fields(new_config_data)

        # 获取当前配置数据
        config_manager = UniConfigManager()
        if config_manager.has_config_instance(owner_name):
            current_config_instance = config_manager.get_config_instance_not_none(
                owner_name
            )
            current_config_data = current_config_instance.model_dump()
        else:
            # 如果还没有配置实例，则加载
            current_config_instance = await config_manager.get_config(owner_name)
            current_config_data = current_config_instance.model_dump()

        current_flat_config_data = flatten_config_fields(current_config_data)
        current_hash = calculate_config_hash(current_flat_config_data)

        # 检查哈希是否匹配，防止并发冲突
        if provided_hash != current_hash:
            return fail(
                409,
                "配置已被其他用户修改，请刷新页面后重试",
                data={"current_hash": current_hash},
            )

        # 获取配置类
        if not config_manager.has_config_class(owner_name):
            return fail(404, f"插件 {owner_name} 未注册配置类")

        config_class = config_manager.get_config_class_by_name(owner_name)
        assert config_class is not None

        # 将部分更新的数据合并到当前配置（增量保存）
        merged_config = deep_merge(current_config_data, nested_config_data)

        # 验证并创建新的配置实例
        new_config_instance = config_class.model_validate(merged_config)

        # 保存配置实例
        await config_manager.loads_config(new_config_instance, owner_name)

        # 保存到文件
        await config_manager.save_config(owner_name)

        # 计算新的哈希值（基于完整合并后的展平配置）
        merged_flat = flatten_config_fields(merged_config)
        new_hash = calculate_config_hash(merged_flat)

        return ok("配置保存成功", data={"hash": new_hash})

    except Exception:
        logger.exception("Failed to save plugin config")
        return fail(500, "保存配置失败")
