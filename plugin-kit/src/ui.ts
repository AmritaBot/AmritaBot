/**
 * 宿主 UI 组件包的插件侧入口。
 *
 * 构建插件时，build.ts 会把对 `@amrita/webui-plugin-kit/ui` 的 import
 * 换成一个虚拟模块 —— 内容是从 `window.__AMRITA_HOST__.UI` 取值的再导出。
 * 因此这里只是编辑器与 tsc 的类型来源，运行时并不执行本文件。
 *
 * 类型来自 @amrita/ui：组件的 props 与宿主用的是同一份声明，
 * 不再统一降级成 any。
 */

export * from "@amrita/ui";
