import { Table, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { InspectionSummaryPayload } from "@/types";

interface Props {
  payload: InspectionSummaryPayload;
}

export function InspectionSummaryCard({ payload }: Props) {
  const { filename, rowCount, colCount, columns } = payload;

  // Columns with quality issues (>5% nulls)
  const issueColumns = columns.filter((c) => c.nullPct > 5);

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-brand-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
            <Table className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Dataset Inspection</p>
            <p className="truncate text-[12px] text-ink-muted">{filename}</p>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-px bg-[var(--line)]">
          {[
            { label: "Rows", value: rowCount.toLocaleString() },
            { label: "Columns", value: colCount.toLocaleString() },
            { label: "Issues", value: issueColumns.length.toString() },
          ].map(({ label, value }) => (
            <div key={label} className="bg-[var(--surface-primary)] px-4 py-3 text-center">
              <p className="text-[18px] font-bold text-ink">{value}</p>
              <p className="text-[11px] text-ink-muted">{label}</p>
            </div>
          ))}
        </div>

        {/* Column quality list */}
        {issueColumns.length > 0 && (
          <div className="border-t border-[var(--line)] px-4 py-3">
            <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-amber-700">
              <AlertTriangle className="h-3.5 w-3.5" />
              Columns with quality issues
            </p>
            <div className="space-y-1.5">
              {issueColumns.slice(0, 8).map((col) => (
                <div key={col.name} className="flex items-center justify-between text-[12px]">
                  <span className="truncate font-mono text-ink-secondary">{col.name}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px] border-[var(--line)]">
                      {col.dtype}
                    </Badge>
                    <span className="text-amber-600 font-medium">
                      {col.nullPct.toFixed(1)}% null
                    </span>
                  </div>
                </div>
              ))}
              {issueColumns.length > 8 && (
                <p className="text-[11px] text-ink-muted">
                  +{issueColumns.length - 8} more columns
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
