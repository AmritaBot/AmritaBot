import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, X } from "lucide-react";
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

/** list 字段：条目列表编辑器（每项一行 Input + 删除，底部添加按钮） */
function ListEditor({
  value,
  onChange,
}: {
  value: FieldValue;
  onChange: (v: string[]) => void;
}) {
  const items = toStrArray(value);

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
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            value={item}
            onChange={(e) => update(i, e.target.value)}
            onBlur={(e) => cleanItem(i, e.target.value)}
            className="font-mono text-xs"
            placeholder={`条目 ${i + 1}`}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
            onClick={() => remove(i)}
            aria-label={`删除条目 ${i + 1}`}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="mr-1 h-4 w-4" /> 添加条目
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

  // Literal 枚举 → Select
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

  // 布尔 → Switch
  if (type === "bool") {
    return (
      <Switch
        checked={value === true || value === "true"}
        onCheckedChange={(checked: boolean) => onChange(checked)}
      />
    );
  }

  // 列表字段 → 条目列表编辑器（逐项可编辑/删除/添加）
  if (type === "list" || Array.isArray(value)) {
    return <ListEditor value={value} onChange={(v) => onChange(v)} />;
  }

  // 字典 → JSON 文本编辑
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

  // 数字 → number input
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

  const { data, isLoading, error } = useQuery({
    queryKey: ["confedit-schema", owner_name],
    queryFn: () => api.get<ConfeditSchemaData>(`/api/confedit/${encodeURIComponent(owner_name ?? "")}/schema`),
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

  const values = changed ? draft : initialValues;

  const setValue = (name: string, v: FieldValue) => {
    setChanged(true);
    setDraft((d) => ({ ...d, [name]: v }));
  };

  /** 提交前清理：所有 list 数组字段过滤空条目 */
  function cleanForSubmit(config: Record<string, FieldValue>): Record<string, FieldValue> {
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
      void queryClient.invalidateQueries({ queryKey: ["confedit-schema", owner_name] });
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
    return (
      <p className="text-destructive">加载配置失败：{error.message}</p>
    );
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
        <CardContent className="divide-y">
          {schema.fields.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              该插件没有可配置字段
            </p>
          )}
          {schema.fields.map((field) => (
            <div
              key={field.name}
              className="grid gap-3 py-4 md:grid-cols-[minmax(180px,1fr)_2fr]"
            >
              <div className="min-w-0">
                <Label className="font-mono text-xs">{field.name}</Label>
                {field.description && (
                  <CardDescription className="mt-1 break-words">{field.description}</CardDescription>
                )}
              </div>
              <FieldEditor
                field={field}
                value={values[field.name] ?? null}
                onChange={(v) => setValue(field.name, v)}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      {changed && (
        <p className="text-xs text-muted-foreground">
          有未保存的修改
        </p>
      )}
    </div>
  );
}
