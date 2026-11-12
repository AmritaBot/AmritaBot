/**
 * 插件运行时小工具：样式注入、API 客户端、宿主能力探测。
 *
 * 这些是每个插件都会做一遍的事，收在这里免得各写一套。
 * 不依赖任何宿主内部路径，只用 window.__AMRITA_HOST__ 与同源 Cookie。
 */

import { getHost } from "./host";

/** 注入插件样式表；同一 id 只注入一次，重复挂载不会塞进多份 */
export function injectCss(href: string, id = "amrita-plugin-css"): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
}

/** 注入一段内联样式（比外链省一次请求，适合几十行的插件样式） */
export function injectStyleText(
  css: string,
  id = "amrita-plugin-style",
): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(id)) return;
  const style = document.createElement("style");
  style.id = id;
  style.textContent = css;
  document.head.appendChild(style);
}

/** 统一响应结构，与宿主 lib/api.ts 一致 */
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  success: boolean;
  data: T;
}

export class PluginApiError extends Error {
  code: number;
  data: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "PluginApiError";
    this.code = code;
    this.data = data;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  let body: ApiResponse<T>;
  try {
    body = (await res.json()) as ApiResponse<T>;
  } catch {
    throw new PluginApiError(res.status, `请求失败 (HTTP ${res.status})`);
  }

  if (!res.ok || !body.success) {
    throw new PluginApiError(
      body.code ?? res.status,
      body.message ?? "请求失败",
      body.data,
    );
  }
  return body.data;
}

/** 插件专用 API 客户端，用法与宿主 api 一致，但只返回 data */
export const pluginApi = {
  get<T>(path: string) {
    return request<T>(path);
  },
  post<T>(path: string, data?: unknown) {
    return request<T>(path, {
      method: "POST",
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  },
};

/** 宿主是否提供了某个可选运行时依赖（如 React Query / lucide-react） */
export function hostHas(field: keyof ReturnType<typeof getHost>): boolean {
  return Boolean(getHost()[field]);
}
