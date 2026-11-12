/**
 * 宿主 UI 组件包的插件侧入口。
 *
 * 构建插件时，build.ts 会把对 `@amrita/webui-plugin-kit/ui` 的 import
 * 换成一个虚拟模块 —— 内容是按 UI_EXPORTS 生成的、从
 * `window.__AMRITA_HOST__.UI` 取值的再导出。
 *
 * 于是组件实现与 className 都来自宿主源码，插件观感天然与宿主一致，
 * 产物里也不会多出一份组件代码。
 *
 * 本文件只在编辑器与 tsc 下用于解析类型；运行时用的是虚拟模块，不等价于它。
 * 组件 props 的精确类型不随套件分发，因此这里统一用宽松类型。
 */

import { UI_EXPORTS } from "./ui-exports";

type AnyComponent = any;

export const Badge: AnyComponent = undefined;
export const badgeVariants: AnyComponent = undefined;
export const Button: AnyComponent = undefined;
export const buttonVariants: AnyComponent = undefined;
export const Card: AnyComponent = undefined;
export const CardAction: AnyComponent = undefined;
export const CardContent: AnyComponent = undefined;
export const CardDescription: AnyComponent = undefined;
export const CardFooter: AnyComponent = undefined;
export const CardHeader: AnyComponent = undefined;
export const CardTitle: AnyComponent = undefined;
export const Dialog: AnyComponent = undefined;
export const DialogTrigger: AnyComponent = undefined;
export const DialogClose: AnyComponent = undefined;
export const DialogContent: AnyComponent = undefined;
export const DialogHeader: AnyComponent = undefined;
export const DialogFooter: AnyComponent = undefined;
export const DialogTitle: AnyComponent = undefined;
export const DialogDescription: AnyComponent = undefined;
export const Input: AnyComponent = undefined;
export const Label: AnyComponent = undefined;
export const Select: AnyComponent = undefined;
export const SelectContent: AnyComponent = undefined;
export const SelectGroup: AnyComponent = undefined;
export const SelectItem: AnyComponent = undefined;
export const SelectLabel: AnyComponent = undefined;
export const SelectScrollDownButton: AnyComponent = undefined;
export const SelectScrollUpButton: AnyComponent = undefined;
export const SelectSeparator: AnyComponent = undefined;
export const SelectTrigger: AnyComponent = undefined;
export const SelectValue: AnyComponent = undefined;
export const Separator: AnyComponent = undefined;
export const Skeleton: AnyComponent = undefined;
export const Toaster: AnyComponent = undefined;
export const Switch: AnyComponent = undefined;
export const Table: AnyComponent = undefined;
export const TableHeader: AnyComponent = undefined;
export const TableBody: AnyComponent = undefined;
export const TableHead: AnyComponent = undefined;
export const TableRow: AnyComponent = undefined;
export const TableCell: AnyComponent = undefined;
export const Tabs: AnyComponent = undefined;
export const TabsList: AnyComponent = undefined;
export const TabsTrigger: AnyComponent = undefined;
export const TabsContent: AnyComponent = undefined;
export const Textarea: AnyComponent = undefined;
export const DataTable: AnyComponent = undefined;
export const StatusBadge: AnyComponent = undefined;
export const StatCard: AnyComponent = undefined;
export const ConfirmDialog: AnyComponent = undefined;
export const cn: AnyComponent = undefined;

/** 清单本身也导出，便于插件或调试面板核对宿主提供了哪些组件 */
export { UI_EXPORTS };
