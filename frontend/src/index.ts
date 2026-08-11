import { serve } from "bun";
import tailwindPlugin from "bun-plugin-tailwind";
import path from "path";
import index from "./index.html";

/**
 * 开发服务器（serve.static 模式，让 bun-plugin-tailwind 生效）
 * - 托管前端静态资源 + CSS/Tailwind 编译 + HMR
 * - /api/* 代理到后端 NoneBot 服务（默认 127.0.0.1:11451，可用 AMRITA_API_TARGET 覆盖）
 */

const API_TARGET = process.env.AMRITA_API_TARGET ?? "http://127.0.0.1:11451";
const SRC_DIR = path.join(import.meta.dir, "src");

/** WebSocket 代理：透传 /amrita/ui/ws 到后端（Bun 的 ws 转发模式） */
async function proxyWs(
  req: Request,
  server: import("bun").Server,
): Promise<Response> {
  // Bun 支持通过 fetch 到 ws:// 目标做全双工转发
  const targetWs = API_TARGET.replace(/^http/, "ws");
  return fetch(`${targetWs}/amrita/ui/ws`, {
    headers: req.headers,
    // @ts-expect-error Bun 扩展：upgrade 标志让 fetch 建立 ws 隧道
    upgrade: "websocket",
  });
}

async function proxyApi(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const target = new URL(url.pathname + url.search, API_TARGET);
  console.log(`[proxy] ${req.method} ${url.pathname} -> ${target.href}`);
  try {
    // 只转发必要的头（cookie / content-type / authorization），避免 Host 等被 Bun 拒绝
    const headers = new Headers();
    for (const name of [
      "cookie",
      "content-type",
      "authorization",
      "accept",
      "x-requested-with",
    ]) {
      const v = req.headers.get(name);
      if (v) headers.set(name, v);
    }
    const res = await fetch(target, {
      method: req.method,
      headers,
      body:
        req.method === "GET" || req.method === "HEAD"
          ? undefined
          : await req.arrayBuffer(),
      redirect: "manual",
    });
    console.log(`[proxy] <- ${res.status} ${url.pathname}`);
    // 转发 Set-Cookie（后端登录下发 httpOnly Cookie）
    const resHeaders = new Headers(res.headers);
    return new Response(res.body, {
      status: res.status,
      headers: resHeaders,
    });
  } catch (e) {
    console.error(`[proxy] ${req.method} ${url.pathname} -> 代理失败:`, e);
    return Response.json(
      {
        code: 502,
        message: "代理后端失败，请确认 bot 已启动",
        success: false,
        data: null,
      },
      { status: 502 },
    );
  }
}

const server = serve({
  // serve.static 模式：static 目录下的 .css 走 bun-plugin-tailwind 管道（bunfig [serve.static]）
  static: {
    "/src": SRC_DIR,
  },
  routes: {
    // API 代理（通配符，须在 "/*" 之前）
    "/api/*": proxyApi,

    // SPA fallback
    "/*": index,
  },
  // WebSocket 代理：/amrita/ui/ws → 后端（Bun 原生支持 ws 转发）
  async fetch(req, server) {
    const url = new URL(req.url);
    if (
      url.pathname === "/amrita/ui/ws" &&
      req.headers.get("upgrade") === "websocket"
    ) {
      return await proxyWs(req, server);
    }
    return server.fetch(req);
  },
  plugins: [tailwindPlugin],

  development: process.env.NODE_ENV !== "production" && {
    // Enable browser hot reloading in development
    hmr: true,

    // Echo console logs from the browser to the server
    console: true,
  },
});

console.log(`🚀 Dev server running at ${server.url}`);
console.log(`🔄 /api/* proxied to ${API_TARGET}`);
