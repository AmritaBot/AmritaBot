import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { cp, readFile, readdir, rm } from "node:fs/promises";
import path from "node:path";
import { defineConfig } from "vite";

// 生产产物随 pip 包分发，build 与 preview 的 base 是 /static/，dev 用根路径
const FRONTEND_DIR = import.meta.dirname;
const SRC_DIR = path.resolve(FRONTEND_DIR, "src");
const OUTDIR = path.resolve(
  FRONTEND_DIR,
  "../amrita/plugins/webui/service/static",
);
const API_TARGET = process.env.AMRITA_API_TARGET ?? "http://127.0.0.1:11451";
// images 是 git 跟踪资源，plugins 是外部插件落点，都不归构建管
const KEEP = new Set(["images", "plugins"]);
// 只清理本工具产出的东西，别的一概不碰
const ARTIFACT = /^(assets$|index\.html$)|\.(js|css|map)$/;
const MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
};

export default defineConfig(({ command, isPreview }) => {
  const buildMode = command === "build" || isPreview;
  let finalOut = OUTDIR;
  let staging = path.join(OUTDIR, ".build-staging");

  return {
    base: buildMode ? "/static/" : "/",
    root: SRC_DIR,
    resolve: { alias: { "@": SRC_DIR } },
    plugins: [
      react(),
      tailwindcss(),
      {
        name: "amrita-stage-build",
        apply: "build",
        // 先把产物写进 staging，构建成功后再替换正式目录
        config(userConfig) {
          const raw = userConfig.build?.outDir ?? OUTDIR;
          finalOut = path.resolve(SRC_DIR, raw);
          if (
            !finalOut.startsWith(FRONTEND_DIR) &&
            !finalOut.startsWith(path.dirname(OUTDIR))
          ) {
            throw new Error(`拒绝写入预期之外的输出目录：${finalOut}`);
          }
          staging = path.join(finalOut, ".build-staging");
          return { build: { outDir: staging, emptyOutDir: true } };
        },
        async closeBundle() {
          const built = await readdir(staging).catch(() => [] as string[]);
          if (built.length === 0) return;
          for (const entry of await readdir(finalOut).catch(
            () => [] as string[],
          )) {
            if (KEEP.has(entry) || entry === ".build-staging") continue;
            if (!ARTIFACT.test(entry)) continue;
            await rm(path.join(finalOut, entry), {
              recursive: true,
              force: true,
            });
          }
          for (const entry of built) {
            await cp(path.join(staging, entry), path.join(finalOut, entry), {
              recursive: true,
            });
          }
          await rm(staging, { recursive: true, force: true });
        },
      },
      {
        name: "amrita-dev-static",
        apply: "serve",
        // dev 只服务源码，/static/images 这类随包资源得手动挂出来
        configureServer(server) {
          server.middlewares.use(async (req, res, next) => {
            const url = req.url?.split("?")[0] ?? "";
            if (!url.startsWith("/static/images/")) return next();
            const file = path.resolve(OUTDIR, url.slice(1));
            if (!file.startsWith(OUTDIR + path.sep)) return next();
            try {
              res.setHeader(
                "Content-Type",
                MIME[path.extname(file)] ?? "application/octet-stream",
              );
              res.end(await readFile(file));
            } catch {
              next();
            }
          });
        },
      },
    ],
    server: {
      port: 3000,
      proxy: {
        "/api": { target: API_TARGET, changeOrigin: true },
        "/amrita": {
          target: API_TARGET,
          changeOrigin: true,
          ws: true,
          // 后端校验 Origin 与 Host 同源；代理改写了 Host，Origin 也得跟着改
          configure(proxy) {
            proxy.on("proxyReqWs", (req) =>
              req.setHeader("origin", API_TARGET),
            );
          },
        },
      },
    },
    preview: {
      port: 3000,
      proxy: {
        "/api": { target: API_TARGET, changeOrigin: true },
        "/amrita": { target: API_TARGET, changeOrigin: true, ws: true },
      },
    },
    build: {
      outDir: OUTDIR,
      sourcemap: true,
      target: "es2020",
      rollupOptions: { input: path.resolve(SRC_DIR, "index.html") },
    },
  };
});
