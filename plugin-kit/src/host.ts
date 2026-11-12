/**
 * 宿主运行时契约：宿主把哪些东西挂在 window.__AMRITA_HOST__，
 * 以及它们各自的版本。插件侧的类型与版本检查都以这里为准。
 *
 * 契约版本号在宿主 installHostGlobals() 里同步递增，
 * 插件构建时写进 bundle，运行期比对，不匹配就在控制台点名，
 * 而不是让 invalid hook call 这种看不出根因的错默默出现。
 */

/** 宿主公共契约版本，插件与宿主必须一致（次版本兼容，主版本不兼容） */
export const HOST_CONTRACT_VERSION = 2;

/** 宿主注入的全局变量名 */
export const HOST_GLOBAL = "__AMRITA_HOST__";

/** 插件在 window 上暴露自身信息的键，便于宿主/调试面板识别 */
export const PLUGIN_GLOBAL_PREFIX = "__AMRITA_PLUGIN__";

/** 宿主暴露的运行时依赖集合（模块名 -> 全局字段名） */
export const HOST_MODULES = {
  react: "React",
  "react-dom": "ReactDOM",
  "react-dom/client": "ReactDOMClient",
  "react/jsx-runtime": "React",
  "react/jsx-dev-runtime": "React",
  "react-router-dom": "ReactRouterDOM",
  "@tanstack/react-query": "ReactQuery",
  "lucide-react": "LucideReact",
} as const;

/**
 * 宿主 UI 组件包不在这里：它没有单一的全局字段形状，
 * 而是按 ui-exports.ts 的清单逐个从 window.__AMRITA_HOST__.UI 取值，
 * 由 build.ts 生成虚拟模块（见 UI_SPECIFIER）。
 */

export type HostModuleId = keyof typeof HOST_MODULES;

/** 宿主全局对象形状（插件侧类型来源） */
export interface AmritaHostGlobals {
  contract: number;
  React: Record<string, unknown>;
  ReactDOM: Record<string, unknown>;
  ReactDOMClient: Record<string, unknown>;
  ReactRouterDOM: Record<string, unknown>;
  ReactQuery?: Record<string, unknown>;
  LucideReact?: Record<string, unknown>;
}

declare global {
  interface Window {
    __AMRITA_HOST__?: AmritaHostGlobals;
  }
}

/** 取宿主全局；缺失时抛出带明确指引的错误 */
export function getHost(): AmritaHostGlobals {
  const host = window.__AMRITA_HOST__;
  if (!host) {
    throw new Error(
      "未找到 window.__AMRITA_HOST__：本模块只能由 AmritaBot WebUI 运行期加载，" +
        "不能直接当普通页面引入。",
    );
  }
  return host;
}

/** 校验契约版本，主版本不同即视为不兼容 */
export function assertHostContract(required = HOST_CONTRACT_VERSION): void {
  const host = getHost();
  const hostMajor = Math.trunc(host.contract ?? 0);
  const reqMajor = Math.trunc(required);
  if (hostMajor !== reqMajor) {
    console.error(
      `[amrita-plugin] 宿主契约版本不兼容：插件要求 ${required}，宿主提供 ${host.contract}。` +
        "页面可能无法正常工作，请联系插件作者或升级 AmritaBot。",
    );
  }
}
