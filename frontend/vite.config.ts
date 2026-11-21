import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { readdir, rm } from "node:fs/promises";
import path from "node:path";
import { defineConfig } from "vite";

/**
 * WebUI 的构建与开发服务器配置。
 *
 * 生产产物输出到插件的 static/ 目录，随 pip 包分发，所以 build 的 base 是 /static/；
 * 开发服务器仍然挂在根路径，避免打开 localhost:3000/static/ 这种别扭地址。
 *
 * 用 Rollup（Vite 内置）而不是 Bun.build：后者在 HTML 入口 + 代码分块下会生成
 * 指不到实际绑定的重导出（浏览器报 “Export 'xxx' is not defined in module”），
 * 之前靠事后改写 index.html 的 script 地址绕开，是补丁；换工具链才是解法。
 */

const FRONTEND_DIR = import.meta.dirname;
const SRC_DIR = path.resolve(FRONTEND_DIR, "src");
const OUTDIR = path.resolve(
  FRONTEND_DIR,
  "../amrita/plugins/webui/service/static",
);
const API_TARGET = process.env.AMRITA_API_TARGET ?? "http://127.0.0.1:11451";
// images 是 git 跟踪的静态资源，plugins 是外部插件产物的落点，都不归本次构建管
const KEEP = new Set(["images", "plugins"]);

let cleanTarget = OUTDIR;

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/" : "/",
  // 以 src 为 root：index.html 就在这一层，入口天然是 /index.html
  root: SRC_DIR,
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "amrita-clean-output",
      // 清理跟着实际 outDir 走：build:local 用 --outDir dist 时不能再清 static/
      configResolved(config) {
        cleanTarget = path.resolve(config.root, config.build.outDir);
      },
      async buildStart() {
        const entries = await readdir(cleanTarget).catch(() => [] as string[]);
        for (const entry of entries) {
          if (KEEP.has(entry)) continue;
          await rm(path.join(cleanTarget, entry), {
            recursive: true,
            force: true,
          });
        }
      },
    },
  ],
  resolve: {
    alias: { "@": SRC_DIR },
  },
  server: {
    port: 3000,
    proxy: {
      // 同源代理：浏览器侧不需要 CORS，cookie 原样透传；WS 直接升级
      "/api": { target: API_TARGET, changeOrigin: true },
      "/amrita": { target: API_TARGET, changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: OUTDIR,
    // 输出目录里还有别人的文件（见 KEEP），不能让 Vite 整个清空
    emptyOutDir: false,
    sourcemap: true,
    target: "es2020",
    rollupOptions: {
      input: path.resolve(SRC_DIR, "index.html"),
    },
  },
}));
