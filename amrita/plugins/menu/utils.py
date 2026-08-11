from nonebot.adapters.onebot.v11 import MessageEvent

from amrita.plugins.perm.API.rules import any_has_permission

from .models import MatcherData, PluginData


async def _visible(matcher_data: MatcherData, event: MessageEvent, sudo: bool) -> bool:
    """判断某个 matcher 是否对调用者可见

    - show_if 为 None -> 总是可见
    - sudo 模式 -> 强制可见（已由调用方校验 lp.admin）
    - 否则 -> 检查调用者是否满足 show_if 权限节点
    """
    if matcher_data.show_if is None or sudo:
        return True
    return await (any_has_permission(matcher_data.show_if))(event)


async def generate_menu(
    plugins: list[PluginData],
    *,
    event: MessageEvent,
    sudo: bool = False,
) -> list[str]:
    """生成菜单文本

    Args:
        plugins: 插件列表
        event: 调用者事件（用于权限节点判断）
        sudo: 是否完整模式（--sudo，展示所有 show_if 项，调用方需先校验 lp.admin）

    Returns:
        菜单文本列表
    """
    head = "这是菜单列表，包含所有可用的功能和用法。\n"
    head += "模块列表：\n\n"
    for plugin in plugins:
        if not plugin.metadata or not plugin.matcher_grouping:
            continue
        # 插件有任意可见项才列入模块列表
        visible = False
        for matcher_group in plugin.matcher_grouping.values():
            for m in matcher_group:
                if await _visible(m, event, sudo):
                    visible = True
                    break
            if visible:
                break
        if visible:
            head += f"\n{plugin.metadata.name}"

    menu_datas: list[str] = [head.strip()]
    for plugin in plugins:
        if not plugin.matcher_grouping or not plugin.metadata:
            continue

        plugin_title = f"{plugin.metadata.name}\n\n"
        plugin_markdown = plugin_title
        for matcher_group in plugin.matcher_grouping.values():
            for matcher_data in matcher_group:
                if not await _visible(matcher_data, event, sudo):
                    continue
                plugin_markdown += f" {matcher_data.name}: {matcher_data.description}"
                if matcher_data.usage:
                    plugin_markdown += f"\n - 用法: {matcher_data.usage}"
                plugin_markdown += "\n"
        if plugin_markdown == plugin_title:
            # 该插件所有项均不可见，跳过空插件块
            continue
        menu_datas.append(plugin_markdown.strip())

    return menu_datas
