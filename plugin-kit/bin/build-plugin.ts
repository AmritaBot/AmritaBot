#!/usr/bin/env bun
/**
 * 命令行入口：在插件项目根目录执行 `bunx amrita-plugin-build`。
 *
 * 读取可选的 amrita-plugin.json 配置：
 *   { "entry": "src/index.tsx", "outdir": "dist", "assets": ["src/index.css"] }
 * 命令行参数优先于配置文件。
 */

import path from "path";
import { existsSync } from "fs";
import { buildPlugin } from "../src/build";

function parseArgs(argv: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (!arg.startsWith("--")) continue;
    const [k, v] = arg.slice(2).split("=", 2);
    if (v !== undefined) out[k!] = v;
    else if (argv[i + 1] && !argv[i + 1]!.startsWith("--")) {
      out[k!] = argv[++i]!;
    } else out[k!] = "true";
  }
  return out;
}

const cwd = process.cwd();
const cfgPath = path.join(cwd, "amrita-plugin.json");
let cfg: Record<string, unknown> = {};

if (existsSync(cfgPath)) {
  cfg = (await Bun.file(cfgPath).json()) as Record<string, unknown>;
} else {
  console.log("未找到 amrita-plugin.json，使用默认约定（src/index.tsx -> dist/）");
}

const args = parseArgs(process.argv.slice(2));

const outdir = args.outdir ?? (cfg.outdir as string | undefined) ?? "dist";
const entry = args.entry ?? (cfg.entry as string | undefined) ?? "src/index.tsx";
const assets =
  args.assets !== undefined
    ? args.assets.split(",").filter(Boolean)
    : ((cfg.assets as string[] | undefined) ?? []);

console.log(`构建插件：${entry} -> ${outdir}`);

const files = await buildPlugin({
  entry,
  outdir,
  assets,
  minify: args.minify !== "false",
});

for (const f of files) {
  const size = (await Bun.file(f).arrayBuffer()).byteLength;
  console.log(`  ${path.relative(cwd, f)}  ${size} B`);
}

if (files.length === 0) console.warn("没有生成任何产物");
