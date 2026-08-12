import { useState } from "react";
import { AlertTriangle, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

/**
 * 权限编辑器：结构化行编辑（替代直接编辑权限字符串）
 *
 * - 每行 = 权限节点（Input）+ 允许/拒绝（Switch）+ 删除
 * - 空占位行：允许存在但保持唯一（已有空行时不重复添加），保存时自动过滤
 * - 无法解析的行（注释、单节点等）：保留为只读原始行，保存时原样写回，不静默丢弃
 * - 行 key 使用唯一 id（非 index），保证占位行增删时状态不串位
 */

interface PermRow {
  /** 行唯一 id，仅作 React key，不参与序列化 */
  id: string;
  /** 权限节点路径，如 chat.send */
  node: string;
  /** true=允许，false=拒绝 */
  has: boolean;
  /** 无法解析的原始行（如注释 `# ...`、单节点行），序列化时原样写回 */
  raw?: string;
}

/** 行 id：优先 crypto.randomUUID，不可用（旧浏览器/非安全上下文）时降级时间戳+随机数 */
function createPermRowId(): string {
  const cryptoObj =
    typeof globalThis !== "undefined"
      ? (
          globalThis as {
            crypto?: { randomUUID?: () => string };
          }
        ).crypto
      : undefined;
  if (cryptoObj && typeof cryptoObj.randomUUID === "function") {
    return cryptoObj.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function newRow(): PermRow {
  return { id: createPermRowId(), node: "", has: false };
}

/** 解析权限字符串（每行 `node true/false`）为行数组；无法解析的行保留原文 */
function parsePermStr(permStr: string): PermRow[] {
  const rows: PermRow[] = [];
  for (const line of permStr.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\s+/);
    const [node, state] = parts;
    if (parts.length >= 2 && node && state) {
      rows.push({
        id: createPermRowId(),
        node,
        has: state.toLowerCase() === "true",
      });
    } else {
      // 注释 / 单节点等无法解析的行：保留原文，避免保存时静默丢失
      rows.push({
        id: createPermRowId(),
        node: "",
        has: false,
        raw: trimmed,
      });
    }
  }
  return rows;
}

/** 序列化行数组为权限字符串（空节点行过滤，原始行原样输出） */
function serializeRows(rows: PermRow[]): string {
  return rows
    .filter((r) => r.node.trim() !== "" || r.raw !== undefined)
    .map((r) => r.raw ?? `${r.node.trim()} ${r.has ? "true" : "false"}`)
    .join("\n");
}

export function PermissionEditor({
  initial,
  onSubmit,
  submitting,
}: {
  /** 初始权限字符串（每行 `node true/false`） */
  initial: string;
  onSubmit: (permStr: string) => void;
  submitting: boolean;
}) {
  const [rows, setRows] = useState<PermRow[]>(() => parsePermStr(initial));
  const [dirty, setDirty] = useState(false);

  function updateNode(id: string, node: string) {
    setDirty(true);
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, node } : r)));
  }

  function updateHas(id: string, has: boolean) {
    setDirty(true);
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, has } : r)));
  }

  function removeRow(id: string) {
    setDirty(true);
    setRows((rs) => rs.filter((r) => r.id !== id));
  }

  function addRow() {
    // 空占位行保持唯一：已有空节点行时不重复添加
    if (rows.some((r) => r.node.trim() === "")) return;
    setDirty(true);
    setRows((rs) => [...rs, newRow()]);
  }

  return (
    <div className="space-y-3">
      {rows.length === 0 && (
        <p className="flex min-h-9 items-center rounded-md border border-dashed px-3 text-xs text-muted-foreground">
          （暂无权限，点击下方「添加权限」开始）
        </p>
      )}
      {rows.map((row) =>
        row.raw !== undefined ? (
          /* 无法解析的原始行：只读展示（可删除），保存时原样保留 */
          <div
            key={row.id}
            className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 px-3 py-2"
          >
            <AlertTriangle className="h-4 w-4 shrink-0 text-muted-foreground" />
            <code
              className="flex-1 truncate font-mono text-xs text-muted-foreground"
              title={row.raw}
            >
              {row.raw}
            </code>
            <span className="shrink-0 text-[10px] text-muted-foreground">
              原样保留
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
              onClick={() => removeRow(row.id)}
              aria-label="删除该行"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <div key={row.id} className="flex items-center gap-2">
            <Input
              value={row.node}
              onChange={(e) => updateNode(row.id, e.target.value)}
              className="font-mono text-xs"
              placeholder="权限节点，如 chat.send"
              spellCheck={false}
            />
            <span
              className={cn(
                "flex h-8 w-16 shrink-0 items-center justify-center gap-1.5 rounded-md border px-2 text-xs font-medium",
                row.has
                  ? "border-primary/30 bg-primary/10 text-primary"
                  : "border-destructive/30 bg-destructive/10 text-destructive",
              )}
            >
              {row.has ? "允许" : "拒绝"}
            </span>
            <Switch
              checked={row.has}
              onCheckedChange={(checked) => updateHas(row.id, checked)}
              aria-label={`${row.node || "空节点"} 权限开关`}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
              onClick={() => removeRow(row.id)}
              aria-label="删除该权限"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ),
      )}
      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" size="sm" onClick={addRow}>
          <Plus className="mr-1 h-4 w-4" /> 添加权限
        </Button>
        <Button
          onClick={() => onSubmit(serializeRows(rows))}
          disabled={submitting || !dirty}
        >
          {submitting ? "保存中…" : "保存"}
        </Button>
      </div>
    </div>
  );
}
