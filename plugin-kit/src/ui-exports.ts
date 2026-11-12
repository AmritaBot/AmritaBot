/**
 * 宿主 UI 组件包导出的组件名清单。
 *
 * 这是插件侧与宿主 ui-kit 的唯一对照表：构建插件时按它生成
 * "从 window.__AMRITA_HOST__.UI 取值"的再导出模块。
 *
 * 增删宿主组件时要同时改这里和宿主 frontend/src/lib/ui-kit.ts，
 * 否则插件会拿到 undefined（构建期会检查缺失名并直接报错）。
 */

export const UI_EXPORTS = [
  // ui 原子组件
  "Badge",
  "badgeVariants",
  "Button",
  "buttonVariants",
  "Card",
  "CardAction",
  "CardContent",
  "CardDescription",
  "CardFooter",
  "CardHeader",
  "CardTitle",
  "Dialog",
  "DialogTrigger",
  "DialogClose",
  "DialogContent",
  "DialogHeader",
  "DialogFooter",
  "DialogTitle",
  "DialogDescription",
  "Input",
  "Label",
  "Select",
  "SelectContent",
  "SelectGroup",
  "SelectItem",
  "SelectLabel",
  "SelectScrollDownButton",
  "SelectScrollUpButton",
  "SelectSeparator",
  "SelectTrigger",
  "SelectValue",
  "Separator",
  "Skeleton",
  "Toaster",
  "Switch",
  "Table",
  "TableHeader",
  "TableBody",
  "TableHead",
  "TableRow",
  "TableCell",
  "Tabs",
  "TabsList",
  "TabsTrigger",
  "TabsContent",
  "Textarea",
  // 业务通用件
  "DataTable",
  "StatusBadge",
  "StatCard",
  "ConfirmDialog",
  // 工具函数
  "cn",
] as const;

export type UiExportName = (typeof UI_EXPORTS)[number];
