/**
 * 运行期远程模块加载（WebUI 前端扩展）
 *
 * 后端 `register_page(module_url=...)` 声明的页面，前端在首次访问时用
 * `import()` 拉取 ESM 模块，取 `default` 作为页面组件 —— 插件因此
 * **无需重新构建前端**。
 *
 * 为保证 React 单实例，宿主把运行时依赖挂在 `window.__AMRITA_HOST__`。
 * 插件构建时把这些包设为 external，并在模块顶层把对它们的 import 映射到
 * 宿主全局，例如：
 *
 * ```ts
 * const { React } = window.__AMRITA_HOST__!;
 * export default function Page() {
 *   return React.createElement("div", null, "hello");
 * }
 * ```
 */

import { lazy, type ComponentType } from "react";
import * as React from "react";
import * as ReactDOM from "react-dom";
import * as ReactDOMClient from "react-dom/client";
import * as ReactRouterDOM from "react-router-dom";

/** 宿主暴露给远程模块的运行时依赖 */
export interface AmritaHostGlobals {
  React: typeof React;
  ReactDOM: typeof ReactDOM;
  ReactDOMClient: typeof ReactDOMClient;
  ReactRouterDOM: typeof ReactRouterDOM;
}

declare global {
  interface Window {
    __AMRITA_HOST__?: AmritaHostGlobals;
  }
}

/** 把宿主运行时挂到 window，供远程模块共享（须在首次渲染前调用）。 */
export function installHostGlobals(): void {
  window.__AMRITA_HOST__ = {
    React,
    ReactDOM,
    ReactDOMClient,
    ReactRouterDOM,
  };
}

/** 远程模块形状：只要求一个默认导出的组件 */
interface RemoteModule {
  default?: unknown;
}

/** 同一 URL 只解析一次，避免每次渲染都生成新的 lazy 组件 */
const componentCache = new Map<string, ComponentType>();

/** 按 URL 加载（并缓存）远程页面组件 */
export function loadRemoteComponent(url: string): ComponentType {
  const cached = componentCache.get(url);
  if (cached) return cached;
  const component = lazy(async () => {
    const mod = (await import(/* @vite-ignore */ url)) as RemoteModule;
    if (mod.default === undefined || mod.default === null) {
      throw new Error(`远程模块 ${url} 缺少默认导出组件（export default ...）`);
    }
    return { default: mod.default as ComponentType };
  });
  componentCache.set(url, component);
  return component;
}
