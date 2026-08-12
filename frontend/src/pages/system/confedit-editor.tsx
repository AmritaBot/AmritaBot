import { useEffect, useMemo, useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useBlocker, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ChevronDown,
  ChevronRight,
  GripVertical,
  Plus,
  SearchX,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ConfeditField, ConfeditSchemaData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** schema 驱动的动态配置编辑器 */

type FieldValue = string | number | boolean | string[] | null;

/** 嵌套树节点：叶子为配置字段，非叶子为分组（按 "." 分层） */
interface FieldTreeNode {
  /** 完整路径，如 a.b.c */
  key: string;
  /** 本层名称，如 c */
  label: string;
  /** 叶子字段；分组节点为 null */
  field: ConfeditField | null;
  children: FieldTreeNode[];
}

/** 展平字段（a.b.c）重组为嵌套树 */
function buildFieldTree(fields: ConfeditField[]): FieldTreeNode[] {
  const root: FieldTreeNode[] = [];
  for (const field of fields) {
    const parts = field.name.split(".");
    let level = root;
    let path = "";
    for (const part of parts) {
      path = path ? `${path}.${part}` : part;
      let node = level.find((n) => n.key === path);
      if (!node) {
        node = { key: path, label: part, field: null, children: [] };
        level.push(node);
      }
      if (part === parts[parts.length - 1]) {
        node.field = field;
      } else {
        level = node.children;
      }
    }
  }
  return root;
}

/** 按关键词过滤树：命中叶子保留，组仅保留含命中叶子的分支 */
function filterFieldTree(
  nodes: FieldTreeNode[],
  keyword: string,
): FieldTreeNode[] {
  const lower = keyword.trim().toLowerCase();
  if (!lower) return nodes;
  const result: FieldTreeNode[] = [];
  for (const node of nodes) {
    if (node.field) {
      const hit =
        node.field.name.toLowerCase().includes(lower) ||
        (node.field.description ?? "").toLowerCase().includes(lower);
      if (hit) result.push(node);
    } else {
      const children = filterFieldTree(node.children, keyword);
      if (children.length > 0) result.push({ ...node, children });
    }
  }
  return result;
}

/** 叶子：单个配置字段的编辑行 */
function FieldLeaf({
  node,
  value,
  onValueChange,
}: {
  node: FieldTreeNode;
  value: FieldValue;
  onValueChange: (v: FieldValue) => void;
}) {
  const field = node.field!;
  return (
    <div className="grid gap-3 py-4 md:grid-cols-[minmax(180px,1fr)_2fr]">
      <div className="min-w-0">
        <Label className="font-mono text-xs">{node.label}</Label>
        {node.key !== node.label && (
          <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
            {node.key}
          </p>
        )}
        {field.description && (
          <CardDescription className="mt-1 wrap-break-word">
            {field.description}
          </CardDescription>
        )}
      </div>
      <FieldEditor field={field} value={value} onChange={onValueChange} />
    </div>
  );
}

/** 分组：可折叠的嵌套区块 */
function FieldGroup({
  node,
  values,
  onValueChange,
  forceOpen,
}: {
  node: FieldTreeNode;
  values: Record<string, FieldValue>;
  onValueChange: (name: string, v: FieldValue) => void;
  /** 搜索过滤时强制展开所有分组 */
  forceOpen: boolean;
}) {
  const [open, setOpen] = useState(true);
  const isOpen = forceOpen || open;

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 py-3 text-left"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span className="text-sm font-medium">{node.label}</span>
        <span className="truncate font-mono text-xs text-muted-foreground">
          {node.key}
        </span>
      </button>
      {isOpen && (
        <div className="ml-2 border-l pl-4">
          <div className="divide-y">
            {node.children.map((child) =>
              child.field ? (
                <FieldLeaf
                  key={child.key}
                  node={child}
                  value={values[child.key] ?? null}
                  onValueChange={(v) => onValueChange(child.key, v)}
                />
              ) : (
                <FieldGroup
                  key={child.key}
                  node={child}
                  values={values}
                  onValueChange={onValueChange}
                  forceOpen={forceOpen}
                />
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function parseValue(raw: string, type: string): FieldValue {
  const trimmed = raw.trim();
  if (type === "bool") {
    return trimmed === "true" || trimmed === "1";
  }
  if (type === "int") {
    const n = Number.parseInt(trimmed, 10);
    return Number.isNaN(n) ? null : n;
  }
  if (type === "float") {
    const n = Number.parseFloat(trimmed);
    return Number.isNaN(n) ? null : n;
  }
  return raw;
}

function stringifyValue(value: FieldValue): string {
  if (value === null) return "";
  if (typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return "";
  return String(value);
}

function toStrArray(value: FieldValue): string[] {
  return Array.isArray(value) ? value : [];
}

/** list 字段：条目列表编辑器（逐项可编辑/删除/添加，@dnd-kit 拖拽排序） */
function ListEditor({
  value,
  onChange,
}: {
  value: FieldValue;
  onChange: (v: string[]) => void;
}) {
  const items = toStrArray(value);

  // 指针（鼠标/触屏）拖拽：激活距离 8px 避免与输入框点击/文本选中冲突
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const from = Number(active.id);
    const to = Number(over.id);
    if (from === to || Number.isNaN(from) || Number.isNaN(to)) return;
    onChange(arrayMove(items, from, to));
  }

  function update(index: number, text: string) {
    const next = [...items];
    next[index] = text;
    onChange(next);
  }

  function remove(index: number) {
    onChange(items.filter((_, i) => i !== index));
  }

  function add() {
    // 已存在空条目（含纯空白）时不重复添加
    if (items.some((item) => item.trim() === "")) return;
    onChange([...items, ""]);
  }

  /** 过滤空条目：失焦时以输入框实时值重建该位置，再过滤空白 */
  function cleanItem(index: number, currentText: string) {
    const merged = [...items];
    merged[index] = currentText;
    const next = merged.filter((item) => item.trim() !== "");
    if (next.length !== merged.length) onChange(next);
  }

  return (
    <div className="space-y-2">
      {items.length === 0 && (
        <p className="flex min-h-9 items-center px-3 text-xs text-muted-foreground">
          （空列表）
        </p>
      )}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={items.map((_, i) => String(i))}
          strategy={verticalListSortingStrategy}
        >
          {items.map((item, i) => (
            <SortableRow
              key={i}
              index={i}
              item={item}
              onUpdate={update}
              onRemove={remove}
              onClean={cleanItem}
            />
          ))}
        </SortableContext>
      </DndContext>
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="mr-1 h-4 w-4" /> 添加条目
      </Button>
    </div>
  );
}

/** 单行条目：@dnd-kit sortable 行（拖拽手柄 + 输入框 + 删除） */
function SortableRow({
  index,
  item,
  onUpdate,
  onRemove,
  onClean,
}: {
  index: number;
  item: string;
  onUpdate: (index: number, text: string) => void;
  onRemove: (index: number) => void;
  onClean: (index: number, currentText: string) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: String(index) });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex items-center gap-2 rounded-md ${
        isDragging ? "relative z-10 bg-muted/80 ring-1 ring-primary" : ""
      }`}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        className="shrink-0 cursor-grab touch-none rounded p-0.5 text-muted-foreground hover:text-foreground active:cursor-grabbing"
        aria-label={`拖动排序条目 ${index + 1}`}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <Input
        value={item}
        onChange={(e) => onUpdate(index, e.target.value)}
        onBlur={(e) => onClean(index, e.target.value)}
        className="font-mono text-xs"
        placeholder={`条目 ${index + 1}`}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
        onClick={() => onRemove(index)}
        aria-label={`删除条目 ${index + 1}`}
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}

function FieldEditor({
  field,
  value,
  onChange,
}: {
  field: ConfeditField;
  value: FieldValue;
  onChange: (v: FieldValue) => void;
}) {
  const type = field.type;

  // Literal 枚举 -> Select
  if (field.literal_values) {
    return (
      <Select
        value={stringifyValue(value)}
        onValueChange={(v) => onChange(parseValue(v, "str"))}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder="选择…" />
        </SelectTrigger>
        <SelectContent>
          {field.literal_values.map((opt) => (
            <SelectItem key={opt} value={opt}>
              {opt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  // 布尔 -> Switch
  if (type === "bool") {
    return (
      <Switch
        checked={value === true || value === "true"}
        onCheckedChange={(checked: boolean) => onChange(checked)}
      />
    );
  }

  // 列表字段 -> 条目列表编辑器（逐项可编辑/删除/添加）
  if (type === "list" || Array.isArray(value)) {
    return <ListEditor value={value} onChange={(v) => onChange(v)} />;
  }

  // 字典 -> JSON 文本编辑
  if (type === "dict") {
    const text = JSON.stringify(value);
    return (
      <Input
        value={text}
        onChange={(e) => {
          try {
            onChange(JSON.parse(e.target.value) as FieldValue);
          } catch {
            // 非法 JSON 时不更新
          }
        }}
        className="font-mono text-xs"
        placeholder="JSON 对象"
      />
    );
  }

  // 数字 -> number input
  if (type === "int" || type === "float") {
    return (
      <Input
        type="number"
        step={type === "float" ? "any" : "1"}
        value={stringifyValue(value)}
        onChange={(e) => onChange(parseValue(e.target.value, type))}
      />
    );
  }

  // 默认文本
  return (
    <Input
      value={stringifyValue(value)}
      onChange={(e) => onChange(parseValue(e.target.value, type))}
    />
  );
}

export function ConfeditEditorPage() {
  const { owner_name } = useParams<{ owner_name: string }>();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, FieldValue>>({});
  const [changed, setChanged] = useState(false);
  const [keyword, setKeyword] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["confedit-schema", owner_name],
    queryFn: () =>
      api.get<ConfeditSchemaData>(
        `/api/confedit/${encodeURIComponent(owner_name ?? "")}/schema`,
      ),
    enabled: !!owner_name,
  });

  const schema = data?.data;
  const initialValues = useMemo(() => {
    if (!schema) return {};
    const values: Record<string, FieldValue> = {};
    for (const field of schema.fields) {
      const v = field.current_value;
      values[field.name] =
        typeof v === "string" ||
        typeof v === "number" ||
        typeof v === "boolean" ||
        v === null ||
        Array.isArray(v)
          ? (v as FieldValue)
          : JSON.stringify(v);
    }
    return values;
  }, [schema]);

  /** 展平字段 → 嵌套树（按 "." 分层展示） */
  const tree = useMemo(() => buildFieldTree(schema?.fields ?? []), [schema]);
  const visibleTree = useMemo(
    () => filterFieldTree(tree, keyword),
    [tree, keyword],
  );

  const values = changed ? draft : initialValues;

  const setValue = (name: string, v: FieldValue) => {
    setChanged(true);
    setDraft((d) => {
      // 首次修改以初始值为底，避免切换 draft 时其余字段被置空
      const base = Object.keys(d).length > 0 ? d : initialValues;
      return { ...base, [name]: v };
    });
  };

  // 未保存修改时拦截 SPA 内部导航（侧边栏跳转等），浏览器原生 confirm 确认
  const blocker = useBlocker(changed);
  useEffect(() => {
    if (blocker.state === "blocked") {
      if (window.confirm("有未保存的修改，确定离开吗？")) {
        blocker.proceed();
      } else {
        blocker.reset();
      }
    }
  }, [blocker]);

  // 未保存修改时拦截浏览器刷新/关闭（原生对话框，样式由浏览器决定）
  useEffect(() => {
    if (!changed) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [changed]);

  /** 提交前清理：所有 list 数组字段过滤空条目 */
  function cleanForSubmit(
    config: Record<string, FieldValue>,
  ): Record<string, FieldValue> {
    const cleaned: Record<string, FieldValue> = {};
    for (const [key, v] of Object.entries(config)) {
      cleaned[key] = Array.isArray(v)
        ? v.filter((item) => item.trim() !== "")
        : v;
    }
    return cleaned;
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      api.post(`/api/confedit/${encodeURIComponent(owner_name ?? "")}`, {
        config: cleanForSubmit(values),
        hash: schema?.hash,
      }),
    onSuccess: (res) => {
      toast.success(res.message);
      setChanged(false);
      setDraft({});
      // 刷新 schema：UI 立即显示服务器最新值（否则表单停留在旧值，误以为保存失败）
      void queryClient.invalidateQueries({
        queryKey: ["confedit-schema", owner_name],
      });
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.code === 409) {
        toast.error(e.message, {
          description: "配置已被其他用户修改，请刷新页面后重试",
        });
      } else {
        toast.error(e.message);
      }
    },
  });

  if (isLoading || !schema) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error) {
    return <p className="text-destructive">加载配置失败：{error.message}</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            配置编辑器：{owner_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            配置类 {schema.class_name} · {schema.fields.length} 个字段
          </p>
        </div>
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={!changed || saveMutation.isPending}
        >
          {saveMutation.isPending ? "保存中…" : "保存配置"}
        </Button>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 pb-2">
          <CardTitle className="text-base">配置项</CardTitle>
          <Input
            className="h-9 w-64"
            placeholder="搜索配置项…"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </CardHeader>
        <CardContent>
          {schema.fields.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              该插件没有可配置字段
            </p>
          ) : visibleTree.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
              <SearchX className="h-8 w-8" />
              <p className="text-sm">没有匹配的配置项</p>
            </div>
          ) : (
            <div className="divide-y">
              {visibleTree.map((node) =>
                node.field ? (
                  <FieldLeaf
                    key={node.key}
                    node={node}
                    value={values[node.key] ?? null}
                    onValueChange={(v) => setValue(node.key, v)}
                  />
                ) : (
                  <FieldGroup
                    key={node.key}
                    node={node}
                    values={values}
                    onValueChange={setValue}
                    forceOpen={!!keyword.trim()}
                  />
                ),
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {changed && (
        <p className="text-xs text-muted-foreground">有未保存的修改</p>
      )}
    </div>
  );
}
