/**
 * 统一 API 客户端
 *
 * - 同源部署，携带 httpOnly Cookie（credentials: "include"）
 * - 后端统一响应 { code, message, success, data }
 * - 401 统一处理：清空登录态并跳转登录页
 */

export class ApiError extends Error {
  code: number;
  data: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.data = data;
  }
}

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  success: boolean;
  data: T;
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<ApiResponse<T>> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  if (res.status === 401) {
    onUnauthorized?.();
  }

  let body: ApiResponse<T>;
  try {
    body = (await res.json()) as ApiResponse<T>;
  } catch {
    throw new ApiError(res.status, `请求失败 (HTTP ${res.status})`);
  }

  if (!res.ok || !body.success) {
    throw new ApiError(
      body.code ?? res.status,
      body.message ?? "请求失败",
      body.data,
    );
  }
  return body;
}

export const api = {
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
