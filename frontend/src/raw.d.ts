/**
 * Bun ?raw 导入类型声明：`import x from "./file?raw"` 返回文件文本内容。
 */
declare module "*?raw" {
  const content: string;
  export default content;
}
