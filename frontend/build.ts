#!/usr/bin/env bun
import plugin from "bun-plugin-tailwind";
import { existsSync } from "fs";
import { readdir, rm } from "fs/promises";
import path from "path";

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`
🏗️  Bun Build Script

Usage: bun run build.ts [options]

Common Options:
  --outdir <path>          Output directory (default: "dist")
  --minify                 Enable minification (or --minify.whitespace, --minify.syntax, etc)
  --sourcemap <type>      Sourcemap type: none|linked|inline|external
  --target <target>        Build target: browser|bun|node
  --format <format>        Output format: esm|cjs|iife
  --splitting              Enable code splitting
  --packages <type>        Package handling: bundle|external
  --public-path <path>     Public path for assets
  --env <mode>             Environment handling: inline|disable|prefix*
  --conditions <list>      Package.json export conditions (comma separated)
  --external <list>        External packages (comma separated)
  --banner <text>          Add banner text to output
  --footer <text>          Add footer text to output
  --define <obj>           Define global constants (e.g. --define.VERSION=1.0.0)
  --help, -h               Show this help message

Example:
  bun run build.ts --outdir=dist --minify --sourcemap=linked --external=react,react-dom
`);
  process.exit(0);
}

const toCamelCase = (str: string): string =>
  str.replace(/-([a-z])/g, (g) => g[1].toUpperCase());

const parseValue = (value: string): any => {
  if (value === "true") return true;
  if (value === "false") return false;

  if (/^\d+$/.test(value)) return parseInt(value, 10);
  if (/^\d*\.\d+$/.test(value)) return parseFloat(value);

  if (value.includes(",")) return value.split(",").map((v) => v.trim());

  return value;
};

function parseArgs(): Partial<Bun.BuildConfig> {
  const config: Partial<Bun.BuildConfig> = {};
  const args = process.argv.slice(2);

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === undefined) continue;
    if (!arg.startsWith("--")) continue;

    if (arg.startsWith("--no-")) {
      const key = toCamelCase(arg.slice(5));
      config[key] = false;
      continue;
    }

    if (
      !arg.includes("=") &&
      (i === args.length - 1 || args[i + 1]?.startsWith("--"))
    ) {
      const key = toCamelCase(arg.slice(2));
      config[key] = true;
      continue;
    }

    let key: string;
    let value: string;

    if (arg.includes("=")) {
      [key, value] = arg.slice(2).split("=", 2) as [string, string];
    } else {
      key = arg.slice(2);
      value = args[++i] ?? "";
    }

    key = toCamelCase(key);

    if (key.includes(".")) {
      const [parentKey, childKey] = key.split(".");
      config[parentKey] = config[parentKey] || {};
      config[parentKey][childKey] = parseValue(value);
    } else {
      config[key] = parseValue(value);
    }
  }

  return config;
}

const formatFileSize = (bytes: number): string => {
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }

  return `${size.toFixed(2)} ${units[unitIndex]}`;
};

console.log("\n🚀 Starting build process...\n");

const cliConfig = parseArgs();
const outdir = cliConfig.outdir || path.join(process.cwd(), "dist");

// 仅清理构建产物（.js/.css/.map/index.html 等），保留 images/ 等静态资源
if (existsSync(outdir)) {
  console.log(`🗑️ Cleaning previous build artifacts at ${outdir}`);
  const entries = await readdir(outdir);
  for (const entry of entries) {
    if (entry === "images") continue;
    await rm(path.join(outdir, entry), { recursive: true, force: true });
  }
}

const start = performance.now();

const entrypoints = [
  // HTML 入口 + 显式 JS 入口：
  // Bun 对 HTML 中 async script 的编译产物可能被标记为 chunk 而非 entry-point，
  // 导致 index.html 的 <script> 指向 6KB 空壳 chunk（应用不渲染）。
  // 显式把 frontend.tsx 加入 entrypoints 可保证生成真正的 entry-point。
  path.resolve("src", "index.html"),
  path.resolve("src", "frontend.tsx"),
];

const result = await Bun.build({
  entrypoints,
  outdir,
  plugins: [plugin],
  minify: true,
  target: "browser",
  sourcemap: "linked",
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  ...cliConfig,
});

// Bun 1.3.9 HTML 编译 bug 修正：
// HTML 入口 + JS 入口并存时，index.html 的 <script src> 会被重写指向错误的
// 6KB 空壳 chunk（只含 import 但不含依赖链 wrapper），导致应用不渲染。
// 这里把 script 指向 HTML 入口对应的真正 entry-point（540B 的 wrapper，import 全链）。
if (
  result.outputs.some(
    (o) => o.kind === "entry-point" && o.path.endsWith("index.html"),
  )
) {
  const htmlEntry = result.outputs.find(
    (o) => o.kind === "entry-point" && o.path.endsWith(".js") && o.size < 2000,
  );
  const indexPath = path.join(outdir, "index.html");
  if (htmlEntry && existsSync(indexPath)) {
    const html = await Bun.file(indexPath).text();
    const scriptSrc = `src="/static/${path.basename(htmlEntry.path)}"`;
    const fixed = html.replace(/src="[^"]*\.js"/, scriptSrc);
    if (fixed !== html) {
      await Bun.write(indexPath, fixed);
      console.log(
        `🔧 Fixed index.html script → ${path.basename(htmlEntry.path)}`,
      );
    }
  }
}

const end = performance.now();

const outputTable = result.outputs.map((output) => ({
  File: path.relative(process.cwd(), output.path),
  Type: output.kind,
  Size: formatFileSize(output.size),
}));

console.table(outputTable);
const buildTime = (end - start).toFixed(2);

console.log(`\n✅ Build completed in ${buildTime}ms\n`);
