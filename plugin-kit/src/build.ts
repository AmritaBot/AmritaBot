/**
 * 插件构建器：Bun.build + 宿主依赖虚拟化。
 *
 * 纯 ESM 没有 webpack 那种 externals，`import "react"` 会原样留在产物里被浏览器解析。
 * 这里的做法是把 HOST_TABLE 里的每个包映射到 host: 命名空间，
 * 再生成一个"从 window.__AMRITA_HOST__ 取值"的再导出模块顶替它。
 *
 * 具名导出不手写：构建时读取真实包在 node_modules 里的导出名，
 * 逐个生成 `export const X = H.X`，避免漏写某个 hook 导致运行期 undefined。
 *
 * 例外是 jsx-runtime：它是独立模块（`react/jsx-runtime` / `react/jsx-dev-runtime`），
 * 导出并不挂在 React 主命名空间上，必须用 React.createElement 现造一个等价实现。
 */

import path from "path";
import { existsSync } from "fs";
import { mkdir, copyFile, appendFile } from "fs/promises";
import { HOST_CONTRACT_VERSION } from "./host";
import { UI_EXPORTS } from "./ui-exports";

/** 包名 -> 宿主全局字段，与 runtime/host.ts 的 HOST_MODULES 保持一致 */
const HOST_TABLE: Record<string, string> = {
  react: "React",
  "react-dom": "ReactDOM",
  "react-dom/client": "ReactDOMClient",
  "react/jsx-runtime": "React",
  "react/jsx-dev-runtime": "React",
  "react-router-dom": "ReactRouterDOM",
  "@tanstack/react-query": "ReactQuery",
  "lucide-react": "LucideReact",
};

/** jsx-runtime 系列不是"再导出"，要用 createElement 现造 */
const JSX_RUNTIMES = new Set(["react/jsx-runtime", "react/jsx-dev-runtime"]);

/** 宿主 UI 组件包的引用名：插件 import 这个 specifier 取宿主组件 */
const UI_SPECIFIER = "@amrita/webui-plugin-kit/ui";

/** jsx runtime 的等价实现：把 props 摊平后用宿主 React 的 createElement 构造元素 */
const JSX_SHIM = `const R = window.__AMRITA_HOST__?.React;
if (!R) {
  throw new Error("[amrita-plugin] 宿主缺少 React（window.__AMRITA_HOST__.React）");
}
const el = (type, props, key) =>
  R.createElement(type, key == null ? props : { ...props, key });
export const Fragment = R.Fragment;
export const jsx = el;
export const jsxs = el;
export const jsxDEV = el;
export default { Fragment, jsx, jsxs, jsxDEV };
`;

/** 从真实包里读出可用的具名导出（Node 侧 require，只取 key，不执行副作用） */
function readExports(pkg: string, resolveFrom: string): string[] {
  try {
    const req = require.resolve(pkg, { paths: [resolveFrom] });
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const mod = require(req);
    return Object.keys(mod).filter(
      (k) =>
        k !== "default" && k !== "__esModule" && /^[A-Za-z_$][\w$]*$/.test(k),
    );
  } catch {
    return [];
  }
}

/** 生成宿主 UI 组件包的虚拟模块：按清单逐个再导出 */
function uiShim(): string {
  const decls = UI_EXPORTS.map((n) => `export const ${n} = UI.${n};`).join("\n");
  return `const UI = window.__AMRITA_HOST__?.UI;
if (!UI) {
  throw new Error(
    "[amrita-plugin] 宿主未提供 UI 组件包（window.__AMRITA_HOST__.UI），" +
      "可能是因为 AmritaBot 版本过旧"
  );
}
${decls}
export default UI;
`;
}

/** 生成顶替某个宿主包的虚拟模块源码 */
function hostShim(pkg: string, field: string, resolveFrom: string): string {
  if (pkg === UI_SPECIFIER) return uiShim();
  if (JSX_RUNTIMES.has(pkg)) return JSX_SHIM;
  const names = readExports(pkg, resolveFrom);
  const decls = names
    .map((n) => `export const ${n} = H.${field}.${n};`)
    .join("\n");
  return `const H = window.__AMRITA_HOST__;
if (!H || !H.${field}) {
  throw new Error("[amrita-plugin] 宿主缺少依赖 ${pkg}（window.__AMRITA_HOST__.${field}）");
}
export default H.${field};
${decls}
`;
}

/** 构造 Bun 插件：把宿主依赖解析到虚拟模块 */
function hostExternalsPlugin(resolveFrom: string) {
  return {
    name: "amrita-host-externals",
    setup(build: any) {
      build.onResolve({ filter: /.*/ }, (args: any) => {
        // UI 包与宿主依赖走同一条虚拟化路径，只是取值字段不同
        if (args.path === UI_SPECIFIER) {
          return { path: `host:${UI_SPECIFIER}`, namespace: "amrita-host" };
        }
        const field = HOST_TABLE[args.path];
        if (!field) return;
        return { path: `host:${args.path}`, namespace: "amrita-host" };
      });
      build.onLoad({ filter: /.*/, namespace: "amrita-host" }, (args: any) => {
        const pkg = args.path.slice("host:".length);
        // UI 包没有单一的全局字段，走专门的生成器
        if (pkg === UI_SPECIFIER) {
          return { contents: uiShim(), loader: "js" };
        }
        const field = HOST_TABLE[pkg]!;
        return {
          contents: hostShim(pkg, field, resolveFrom),
          loader: "js",
        };
      });
    },
  };
}

export interface BuildPluginOptions {
  /** 插件入口，默认 ./src/index.tsx */
  entry?: string;
  /** 产物目录 */
  outdir: string;
  /** 产物文件名，默认 index.js */
  filename?: string;
  /** 额外要拷贝的静态文件（相对项目根），如 ./src/index.css */
  assets?: string[];
  minify?: boolean;
  /** 用于解析宿主依赖真实导出名的目录，默认取本包同装的 node_modules */
  resolveFrom?: string;
}

/** 构建插件产物，返回生成的产物文件列表 */
export async function buildPlugin(
  options: BuildPluginOptions,
): Promise<string[]> {
  const cwd = process.cwd();
  const entry = path.resolve(cwd, options.entry ?? "src/index.tsx");
  const outdir = path.resolve(cwd, options.outdir);
  const filename = options.filename ?? "index.js";
  const resolveFrom =
    options.resolveFrom ?? path.dirname(require.resolve("react"));

  if (!existsSync(entry)) {
    throw new Error(`插件入口不存在：${entry}`);
  }

  await mkdir(outdir, { recursive: true });

  const result = await Bun.build({
    entrypoints: [entry],
    outdir,
    naming: filename,
    format: "esm",
    target: "browser",
    minify: options.minify ?? true,
    // 生产环境走 jsx-runtime 而非 jsx-dev-runtime：产物更小，且不带 dev 校验
    define: {
      "process.env.NODE_ENV": JSON.stringify("production"),
    },
    plugins: [hostExternalsPlugin(resolveFrom)],
  });

  if (!result.success) {
    for (const log of result.logs) console.error(log);
    throw new Error("插件构建失败");
  }

  const written = result.outputs.map((o) => o.path);

  // 追加契约声明：宿主据此判断插件是否与其兼容，避免版本错配静默失败
  const bundle = path.join(outdir, filename);
  await appendFile(
    bundle,
    `\nexport const amritaHostContract = ${HOST_CONTRACT_VERSION};\n`,
  );

  for (const asset of options.assets ?? []) {
    const from = path.resolve(cwd, asset);
    const to = path.join(outdir, path.basename(from));
    await copyFile(from, to);
    written.push(to);
  }

  return written;
}

export { HOST_TABLE, UI_SPECIFIER };
