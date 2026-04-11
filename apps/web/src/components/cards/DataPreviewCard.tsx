import { Eye, AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DataPreviewPayload } from "@/types";

interface Props {
  payload: DataPreviewPayload;
  onAction?: (action: string, data?: unknown) => void;
}

export function DataPreviewCard({ payload, onAction }: Props) {
  const { columns, rows, totalRows, totalPages, page, pageSize, cellAnnotations } = payload;

  const visibleColumns = columns.slice(0, 8);
  const startRow = (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, totalRows);

  const getAnnotations = (rowIdx: number, colName: string) => {
    const key = `${rowIdx}:${colName}`;
    return cellAnnotations[key] ?? [];
  };

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-blue-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-600">
            <Eye className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Data Preview</p>
            <p className="text-[12px] text-ink-muted">
              Showing {startRow}&ndash;{endRow} of {totalRows.toLocaleString()} rows
            </p>
          </div>
        </div>

        {/* Data table */}
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-[var(--surface-raised)]">
                {visibleColumns.map((col) => (
                  <th
                    key={col.name}
                    className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="truncate">{col.name}</span>
                      {col.hasIssues && (
                        <AlertTriangle className="h-3 w-3 shrink-0 text-amber-500" />
                      )}
                    </div>
                    <Badge
                      variant="outline"
                      className="mt-0.5 text-[9px] border-[var(--line)] font-normal"
                    >
                      {col.dtype}
                    </Badge>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIdx) => (
                <tr key={rowIdx} className="border-t border-[var(--line)]">
                  {visibleColumns.map((col) => {
                    const annotations = getAnnotations(rowIdx, col.name);
                    const hasWarning = annotations.some((a) => a.severity === "warning");
                    const hasError = annotations.some((a) => a.severity === "error");

                    return (
                      <td
                        key={col.name}
                        className={cn(
                          "px-3 py-1.5 text-ink-secondary truncate max-w-[140px]",
                          hasError && "bg-red-50/50",
                          hasWarning && !hasError && "bg-amber-50/50",
                        )}
                      >
                        <div className="flex items-center gap-1">
                          {(hasWarning || hasError) && (
                            <span
                              className={cn(
                                "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                                hasError ? "bg-[#FF6B6B]" : "bg-amber-400",
                              )}
                            />
                          )}
                          <span className="truncate">{String(row[col.name] ?? "")}</span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {columns.length > 8 && (
          <div className="border-t border-[var(--line)] px-4 py-1.5">
            <p className="text-[11px] text-ink-muted">
              +{columns.length - 8} more columns (scroll horizontally)
            </p>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-[var(--line)] bg-[var(--surface-primary)] px-4 py-2.5">
            <span className="text-[12px] text-ink-muted">
              Page {page} of {totalPages}
            </span>
            <div className="flex gap-1.5">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => onAction?.("preview_page", { page: page - 1 })}
                className="h-7 px-2"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => onAction?.("preview_page", { page: page + 1 })}
                className="h-7 px-2"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
