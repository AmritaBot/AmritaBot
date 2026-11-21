/**
 * 组件名清单的唯一来源在 @amrita-constant/ambot-ui。
 *
 * 宿主与构建套件都从这里取同一份清单，不再两处手工同步：
 * 增删控件时只改 UI 包，宿主与插件同时生效。
 */

export { UI_EXPORTS, type UiExportName } from "@amrita-constant/ambot-ui/exports";
