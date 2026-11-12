/**
 * 统一出口。插件作者通常只需要：
 *   import { buildPlugin } from "@amrita/webui-plugin-kit/build";
 *   import { injectCss, pluginApi } from "@amrita/webui-plugin-kit/runtime";
 */

export * from "./host";
export * from "./runtime";
export { buildPlugin, type BuildPluginOptions } from "./build";
