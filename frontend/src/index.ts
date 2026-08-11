import { serve, type Server, type ServerWebSocket } from "bun";
import tailwindPlugin from "bun-plugin-tailwind";
import path from "path";
// ?raw：Bun 1.3.9 的 HTMLBundle.index 字段是源文件路径而非内容，?raw 直接取文件文本
import indexHtml from "./index.html?raw";

/**
 * 开发服务器
 * - 托管前端静态资源 + CSS/Tailwind 按需编译（Bun.build + bun-plugin-tailwind）
 * - /api/* 代理到后端 NoneBot 服务（默认 127.0.0.1:11451，可用 AMRITA_API_TARGET 覆盖）
 * - /amrita/ui/ws 双向桥接（浏览器 ⇄ 后端 WebSocket）
 */

const API_TARGET = process.env.AMRITA_API_TARGET ?? "http://127.0.0.1:11451";
// index.ts 位于 frontend/src/，import.meta.dir 即 src 目录本身
const SRC_DIR = import.meta.dir;

/** 升级时附加的数据（后端 WS 认证需要的 cookie） */
interface WsUpgradeData {
  cookie: string;
}

/** 浏览器 WS -> 后端 WS 的桥接映射 */
const wsBridges = new Map<ServerWebSocket<WsUpgradeData>, WebSocket>();

/** CSS/Tailwind 按需编译：/src/*.css -> 编译产物（bun-plugin-tailwind 管道） */
const cssCache = new Map<string, { body: string; etag: string }>();

async function compileCss(
  filePath: string,
): Promise<{ body: string; etag: string } | null> {
  const cached = cssCache.get(filePath);
  if (cached) return cached;

  try {
    const result = await Bun.build({
      entrypoints: [filePath],
      outdir: "/tmp/amrita-css-build",
      plugins: [tailwindPlugin],
      minify: false,
    });
    // 不依赖 kind 枚举（Bun 版本间不一致）：直接找 .css 输出
    const output = result.outputs.find((o) => o.path.endsWith(".css"));
    if (!output) return null;
    const body = await output.text();
    const etag = `"${result.outputs.map((o) => o.hash).join("-")}"`;
    const entry = { body, etag };
    cssCache.set(filePath, entry);
    return entry;
  } catch (e) {
    console.error(`[css] 编译失败 ${filePath}:`, e);
    return null;
  }
}

/** 静态文件服务：/src/* -> 磁盘文件；.css/.tsx 走编译管道 */
async function serveStatic(urlPath: string): Promise<Response | null> {
  // TSX/TS 入口（如 /frontend.tsx）：Bun.build 编译为 JS
  if (urlPath.endsWith(".tsx") || urlPath.endsWith(".ts")) {
    const abs = path.resolve(SRC_DIR, urlPath.replace(/^\//, ""));
    if (!abs.startsWith(SRC_DIR)) return null;
    if (!(await Bun.file(abs).exists())) return null;
    try {
      const result = await Bun.build({
        entrypoints: [abs],
        outdir: "/tmp/amrita-tsx-build",
        minify: false,
        target: "browser",
        define: {
          "process.env.NODE_ENV": JSON.stringify("development"),
        },
      });
      const output = result.outputs.find((o) => o.kind === "entry-point");
      if (!output) return null;
      const code = await output.text();
      return new Response(code, {
        headers: {
          "Content-Type": "text/javascript;charset=utf-8",
          "Cache-Control": "no-cache",
        },
      });
    } catch (e) {
      console.error(`[tsx] 编译失败 ${abs}:`, e);
      return null;
    }
  }

  const rel = urlPath.startsWith("/src/")
    ? urlPath.slice("/src/".length)
    : null;
  if (!rel) return null;
  const filePath = path.join(SRC_DIR, rel);
  // 防目录穿越
  if (!filePath.startsWith(SRC_DIR)) return null;

  if (rel.endsWith(".css")) {
    const compiled = await compileCss(filePath);
    if (!compiled) return null;
    return new Response(compiled.body, {
      headers: {
        "Content-Type": "text/css;charset=utf-8",
        "Cache-Control": "no-cache",
        ETag: compiled.etag,
      },
    });
  }

  const file = Bun.file(filePath);
  if (!(await file.exists())) return null;
  return new Response(file);
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

const server = serve<WsUpgradeData>({
  // 全部在 fetch 里手动分发：/src/* 静态 -> API 代理 -> WS 升级 -> SPA fallback
  async fetch(req, server) {
    const url = new URL(req.url);
    // WebSocket：升级浏览器连接，交由 websocket handler 桥接到后端
    if (url.pathname === "/amrita/ui/ws") {
      const ok = server.upgrade(req, {
        data: { cookie: req.headers.get("cookie") ?? "" },
      });
      return ok ? undefined : new Response("Upgrade failed", { status: 400 });
    }
    // API 代理
    if (url.pathname.startsWith("/api/")) {
      return await proxyApi(req);
    }
    // 静态资源（/src/*，CSS 走 tailwind 编译管道）
    const staticRes = await serveStatic(url.pathname);
    if (staticRes) return staticRes;
    // SPA fallback（仅 GET）：重写相对脚本路径为绝对路径（深层路由下也能加载入口）
    if (req.method === "GET") {
      const html = indexHtml.replace(
        /src="\.\/frontend\.tsx"/,
        'src="/frontend.tsx"',
      );
      return new Response(html, {
        headers: { "Content-Type": "text/html;charset=utf-8" },
      });
    }
    return new Response("Not Found", { status: 404 });
  },
  // WebSocket 桥接：浏览器 ⇄ 后端（透传消息与关闭）
  websocket: {
    open(ws) {
      const targetWs = API_TARGET.replace(/^http/, "ws");
      // Bun 扩展：WebSocket 构造支持自定义 headers（透传 cookie 供后端认证）
      const backend = new WebSocket(
        `${targetWs}/amrita/ui/ws`,
        // @ts-expect-error Bun 扩展：第二参数可传 { headers }
        { headers: { cookie: ws.data.cookie } },
      );
      wsBridges.set(ws, backend);
      backend.addEventListener("message", (e) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(String(e.data));
      });
      // 透传关闭码（如后端 4401 = token 失效），前端据此停止重连
      backend.addEventListener("close", (e: CloseEvent) => {
        ws.close(e.code, e.reason);
        wsBridges.delete(ws);
      });
      backend.addEventListener("error", () => {
        backend.close();
      });
    },
    message(ws, message) {
      const backend = wsBridges.get(ws);
      if (backend && backend.readyState === WebSocket.OPEN) {
        backend.send(String(message));
      }
    },
    close(ws) {
      const backend = wsBridges.get(ws);
      if (backend) {
        backend.close();
        wsBridges.delete(ws);
      }
    },
  },
  development: process.env.NODE_ENV !== "production" && {
    // Enable browser hot reloading in development
    hmr: true,

    // Echo console logs from the browser to the server
    console: true,
  },
});

console.log(`🚀 Dev server running at ${server.url}`);
console.log(`🔄 /api/* proxied to ${API_TARGET}`);
