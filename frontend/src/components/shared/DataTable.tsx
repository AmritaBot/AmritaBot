import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
}

interface DataTableProps<T extends object> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  emptyText?: string;
}

/** 通用数据表格：loading 骨架屏 + 空态 */
export function DataTable<T extends object>({
  columns,
  data,
  loading,
  emptyText = "暂无数据",
}: DataTableProps<T>) {
  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => (
              <TableHead key={col.key}>{col.header}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                {emptyText}
              </TableCell>
            </TableRow>
          ) : (
            data.map((row, i) => (
              <TableRow key={i}>
                {columns.map((col) => (
                  <TableCell key={col.key}>
                    {col.render
                      ? col.render(row)
                      : String((row as Record<string, unknown>)[col.key] ?? "")}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

/** 状态徽章 */
export function StatusBadge({ status }: { status: string }) {
  const variant = status === "online" || status === "connected" ? "success" : "secondary";
  return <Badge variant={variant}>{status}</Badge>;
}
