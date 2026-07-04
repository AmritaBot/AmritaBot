from typing import Any

from pydantic import BaseModel, Field

from amrita.config_manager import BaseDataManager


def search_perm(data: dict[str, Any], parent_key="", result=None) -> dict[str, Any]:
    """为旧版本适配的权限搜索函数。

    Args:
        data (dict[str, Any]): 原始权限数据
        parent_key (str, optional): 父键. Defaults to "".
        result (_type_, optional): 结果. Defaults to None.

    Returns:
        list[tuple[str, bool]]: 结果
    """
    result = result or {}
    for key, node in data.items():
        current_path = f"{parent_key}.{key}" if parent_key else key
        assert isinstance(node, dict)
        # 检查当前节点权限
        if perm := (node.get("has_permission")) is not None:
            result[current_path] = perm
        elif node.get("explicit_hasnt", False):
            result[current_path] = False
        if node.get("children", {}):
            children = node.get("children", {})
            search_perm(children, current_path, result)
    return result


class Config(BaseModel):
    enable: bool = Field(default=True, description="是否启用插件")
    update_from_json: bool = Field(
        default=True, description="本次启动时，将从JSON中读取并更新权限到数据库中。"
    )
    cache_size: int = Field(default=4096, description="权限缓存大小(修改后重启生效)")


class DataManager(BaseDataManager[Config]):
    config: Config
    config_class: type[Config]
