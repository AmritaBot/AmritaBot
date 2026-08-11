from __future__ import annotations

import hashlib
import json
import logging
from ast import literal_eval
from typing import Any, Literal, get_args, get_origin

from fastapi import Request
from nonebot_plugin_uniconf import UniConfigManager
from pydantic import BaseModel

from amrita.plugins.webui.service.response import fail, ok

from ..main import app

logger = logging.getLogger(__name__)


def flatten_config_fields(
    config_dict: dict, parent_key: str = "", sep: str = "."
) -> dict:
    """格式契约：嵌套配置展平为一级 dict，如 {'a': {'b': 1}} -> {'a.b': 1}。"""
    items = []
    for key, value in config_dict.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.extend(flatten_config_fields(value, new_key, sep).items())
        else:
            items.append((new_key, value))
    return dict(items)


def get_field_info(
    model: type[BaseModel], field_path: str, sep: str = "."
) -> tuple[str, Any, Any]:
    """按路径取 Pydantic 字段的（描述, 默认值, 类型）；路径不存在返回空值。

    路径如 "autoreply.enable" 会递归深入嵌套模型；遇非模型字段即返回当前层。
    """
    field_parts = field_path.split(sep)
    current_model = model
    current_field_info = None

    try:
        for i, part in enumerate(field_parts):
            if not hasattr(current_model, "model_fields"):
                return "", None, None

            model_fields = current_model.model_fields

            if part not in model_fields:
                return "", None, None

            current_field_info = model_fields[part]

            if i < len(field_parts) - 1:
                field_annotation = current_field_info.annotation
                if hasattr(field_annotation, "__origin__"):  # 泛型：无法深入，取当前层
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
        # 路径/类型异常统一视为「无此字段」，不向上抛
        return "", None, None


def extract_literal_values(annotation):
    origin = get_origin(annotation)
    if origin is Literal:
        args = get_args(annotation)
        return list(args)
    return None


def try_parse_value(value_str: Any) -> Any:
    """尽力无害转换字符串（字面量解析），失败原样返回，类型兜底交给 model_validate。"""
    if not isinstance(value_str, str):
        return value_str

    value_str = value_str.strip()

    if not value_str:
        return ""

    try:
        return literal_eval(value_str)
    except (ValueError, SyntaxError):
        return value_str


def unflatten_config_fields(flat_dict: dict, sep: str = ".") -> dict:
    """格式契约：展平的配置还原为嵌套 dict，如 {'a.b': 1} -> {'a': {'b': 1}}。"""
    result = {}
    for key, value in flat_dict.items():
        keys = key.split(sep)
        d = result
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]

        if isinstance(value, str):
            parsed_value = try_parse_value(value)
        else:
            parsed_value = value

        d[keys[-1]] = parsed_value
    return result


def deep_merge(base: dict, overlay: dict) -> dict:
    """overlay 覆盖 base；两边的嵌套 dict 递归合并而非整体替换。"""
    merged = dict(base)
    for key, val in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


async def get_plugin_config_data(plugin_name: str) -> dict[str, Any]:
    config_manager = UniConfigManager()

    if config_manager.has_config_instance(plugin_name):
        config_instance = config_manager.get_config_instance_not_none(plugin_name)
        config_data = config_instance.model_dump()
    else:
        # 未加载过则从存储读取，避免拿不到实例
        config_instance = await config_manager.get_config(plugin_name)
        config_data = config_instance.model_dump()

    return flatten_config_fields(config_data)


def calculate_config_hash(config_data: dict[str, Any]) -> str:
    # 排序键保证同内容同哈希（用于并发冲突检测）
    config_str = json.dumps(config_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(config_str.encode("utf-8")).hexdigest()


@app.get("/api/confedit")
async def list_config_classes():
    """所有已注册配置类的列表（配置管理页）。"""
    config_manager = UniConfigManager()
    config_classes = config_manager.get_config_classes()
    config_list = [
        {"name": plugin_name, "class_name": config_class.__name__}
        for plugin_name, config_class in config_classes.items()
    ]
    return ok("success", data={"configs": config_list})


@app.get("/api/confedit/{owner_name}")
async def get_plugin_config(owner_name: str):
    try:
        config_data = await get_plugin_config_data(owner_name)
        config_hash = calculate_config_hash(config_data)
        return ok("success", data={"config": config_data, "hash": config_hash})
    except Exception:
        logger.exception("Failed to get plugin config")
        return fail(500, "获取配置失败")


@app.post("/api/confedit/{owner_name}")
async def save_plugin_config(owner_name: str, request: Request):
    try:
        request_data = await request.json()
        new_config_data = request_data.get("config", {})
        provided_hash = request_data.get("hash", "")

        nested_config_data = unflatten_config_fields(new_config_data)

        config_manager = UniConfigManager()
        if config_manager.has_config_instance(owner_name):
            current_config_instance = config_manager.get_config_instance_not_none(
                owner_name
            )
            current_config_data = current_config_instance.model_dump()
        else:
            # 未加载过则从存储读取
            current_config_instance = await config_manager.get_config(owner_name)
            current_config_data = current_config_instance.model_dump()

        current_flat_config_data = flatten_config_fields(current_config_data)
        current_hash = calculate_config_hash(current_flat_config_data)

        # 哈希不匹配说明并发修改，拒绝写入
        if provided_hash != current_hash:
            return fail(
                409,
                "配置已被其他用户修改，请刷新页面后重试",
                data={"current_hash": current_hash},
            )

        if not config_manager.has_config_class(owner_name):
            return fail(404, f"插件 {owner_name} 未注册配置类")

        config_class = config_manager.get_config_class_by_name(owner_name)
        assert config_class is not None

        # 增量保存：只覆盖提交的字段，未提交的保留当前值
        merged_config = deep_merge(current_config_data, nested_config_data)

        new_config_instance = config_class.model_validate(merged_config)
        await config_manager.loads_config(new_config_instance, owner_name)
        await config_manager.save_config(owner_name)

        merged_flat = flatten_config_fields(merged_config)
        new_hash = calculate_config_hash(merged_flat)
        return ok("配置保存成功", data={"hash": new_hash})
    except Exception:
        logger.exception("Failed to save plugin config")
        return fail(500, "保存配置失败")


@app.get("/api/confedit/{owner_name}/schema")
async def get_plugin_config_schema(owner_name: str):
    """获取配置字段 schema，前端据此动态生成表单。

    返回每个展平字段的类型、描述、默认值、Literal 选项与当前值。
    """
    try:
        config_manager = UniConfigManager()
        if not config_manager.has_config_class(owner_name):
            return fail(404, f"插件 {owner_name} 未注册配置类")

        config_class = config_manager.get_config_class_by_name(owner_name)
        assert config_class is not None

        # 有实例用当前值，无实例用默认值（未配置过的插件）
        if config_manager.has_config_instance(owner_name):
            config_instance = config_manager.get_config_instance_not_none(owner_name)
            config_data = config_instance.model_dump()
        else:
            config_instance = config_class()
            config_data = config_instance.model_dump()

        flat_config_data = flatten_config_fields(config_data)

        fields = []
        for flat_key, flat_value in flat_config_data.items():
            description, default_value, field_type = get_field_info(
                config_class, flat_key
            )
            if default_value is not None:
                dv_str = str(default_value)
                default_value = dv_str if len(dv_str) <= 20 else dv_str[:20] + "..."

            type_name = type(flat_value).__name__
            literal_values = extract_literal_values(field_type) if field_type else None
            if literal_values:
                type_name = "literal"

            fields.append(
                {
                    "name": flat_key,
                    "description": description,
                    "type": type_name,
                    "literal_values": literal_values,
                    "default": default_value,
                    "current_value": flat_value,
                }
            )

        config_hash = calculate_config_hash(flat_config_data)
        return ok(
            "success",
            data={
                "plugin_name": owner_name,
                "class_name": config_class.__name__,
                "fields": fields,
                "config": flat_config_data,
                "hash": config_hash,
            },
        )
    except Exception:
        logger.exception("Failed to get config schema")
        return fail(500, "获取配置 schema 失败")
