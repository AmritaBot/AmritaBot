/**
 * 运行期远程模块加载（WebUI 前端扩展）
 *
 * 后端 `register_page(module_dir=...)` 声明的页面，前端在首次访问时用
 * `import()` 拉取 ESM 产物，取 `default` 作为页面组件 —— 插件因此
 * **无需重新构建前端**。
 *
 * 为保证 React 单实例，宿主把运行时依赖挂在 `window.__AMRITA_HOST__`。
 * 插件用 @amrita/webui-plugin-kit 构建时，会把这些 import 改写成从该全局取值，
 * 因此插件的产物里不会出现第二份 React。
 *
 * `UI` 是宿主 UI 组件包，由 ui-kit 动态载入后挂上（见 ensureHostUi）：
 * 插件用它拼界面，className 就都来自宿主源码，风格天然对齐。
 *
 * `contract` 是宿主与插件之间的契约版本：主版本不同即视为不兼容。
 * 改 AmritaHostGlobals 的字段或 ui-kit 的导出都要同步 bump。
 */

import { lazy, type ComponentType } from "react";
import * as React from "react";
import * as ReactDOM from "react-dom";
import * as ReactDOMClient from "react-dom/client";
import * as ReactRouterDOM from "react-router-dom";
import * as ReactQuery from "@tanstack/react-query";
import * as LucideReact from "lucide-react";

/**
 * 宿主公共契约版本，与 @amrita/webui-plugin-kit 的 HOST_CONTRACT_VERSION 对齐。
 * 只做加法（加字段/加 UI 组件）时递增次版本位，语义不兼容时递增主版本位。
 */
export const HOST_CONTRACT_VERSION = 2;

/** 宿主暴露给远程模块的运行时依赖 */
export interface AmritaHostGlobals {
  /** 契约版本，插件加载前比对 */
  contract: number;
  React: typeof React;
  ReactDOM: typeof ReactDOM;
  ReactDOMClient: typeof ReactDOMClient;
  ReactRouterDOM: typeof ReactRouterDOM;
  ReactQuery: typeof ReactQuery;
  LucideReact: typeof LucideReact;
  /** 宿主 UI 组件包；未加载时为 undefined，见 ensureHostUi */
  UI?: Record<string, unknown>;
}

declare global {
  interface Window {
    __AMRITA_HOST__?: AmritaHostGlobals;
  }
}

/** 把宿主运行时挂到 window，供远程模块共享（须在首次渲染前调用）。 */
export function installHostGlobals(): void {
  window.__AMRITA_HOST__ = {
    contract: HOST_CONTRACT_VERSION,
    React,
    ReactDOM,
    ReactDOMClient,
    ReactRouterDOM,
    ReactQuery,
    LucideReact,
  };
}

let uiPromise: Promise<void> | null = null;

/**
 * 载入宿主 UI 组件包并挂到全局。
 *
 * 动态 import 而非静态引入：ui-kit 聚合了全部 shadcn 组件，
 * 静态引入会把它们塞进首屏 bundle，而只有插件页才需要。
 */
export function ensureHostUi(): Promise<void> {
  if (uiPromise) return uiPromise;
  uiPromise = import("./ui-kit").then((mod) => {
    const host = window.__AMRITA_HOST__;
    if (!host) {
      throw new Error(
        "installHostGlobals() 未调用：请确认前端入口在渲染前挂载了宿主全局",
      );
    }
    // 组件名清单同时暴露：插件构建套件的导出列表靠它核对，避免漏名
    host.UI = { ...mod, uiExports: Object.keys(mod) };
  });
  return uiPromise;
}

/** 远程模块形状：只要求一个默认导出的组件 */
interface RemoteModule {
  default?: unknown;
  /** 可选：插件声明它要求的契约主版本 */
  amritaHostContract?: number;
}

/** 插件声明的最低契约主版本，取不到时放行（由运行时自行判断） */
function requiredContract(mod: RemoteModule): number | null {
  const v = mod.amritaHostContract;
  return typeof v === "number" ? Math.trunc(v) : null;
}

/** 同一 URL 只解析一次，避免每次渲染都生成新的 lazy 组件 */
const componentCache = new Map<string, ComponentType>();

/** 按 URL 加载（并缓存）远程页面组件 */
export function loadRemoteComponent(url: string): ComponentType {
  const cached = componentCache.get(url);
  if (cached) return cached;
  const component = lazy(async () => {
    // 顺序要紧：插件的模块顶层就会读 window.__AMRITA_HOST__.UI，
    // 必须先把 UI 挂上再执行插件模块
    await ensureHostUi();
    const mod = (await import(/* @vite-ignore */ url)) as RemoteModule;
    if (mod.default === undefined || mod.default === null) {
      throw new Error(`远程模块 ${url} 缺少默认导出组件（export default ...）`);
    }
    const need = requiredContract(mod);
    if (need !== null && need !== Math.trunc(HOST_CONTRACT_VERSION)) {
      // 只警告不拦截：挡住页面反而让用户没法看到插件的报错信息
      console.warn(
        `[amrita] 插件 ${url} 声明契约 ${need}，宿主为 ${HOST_CONTRACT_VERSION}，可能存在不兼容`,
      );
    }
    return { default: mod.default as ComponentType };
  });
  componentCache.set(url, component);
  return component;
}
