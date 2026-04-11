import { GitCompare, Plus, Minus, ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ComparisonPayload } from "@/types";

interface Props {
  payload: ComparisonPayload;
}

export function ComparisonCard({ payload }: Props) {
  const { datasets, summary, columns, statisticalDrift, sampleChanges } = payload;

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-cyan-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-100 text-cyan-600">
            <GitCompare className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Dataset Comparison</p>
            <p className="truncate text-[12px] text-ink-muted">
              {datasets.before.filename} &rarr; {datasets.after.filename}
            </p>
          </div>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-px bg-[var(--line)]">
          {[
            { label: "Rows changed", value: `+${summary.rowsAdded} / -${summary.rowsRemoved}` },
            { label: "Columns changed", value: `+${summary.columnsAdded} / -${summary.columnsRemoved}` },
            { label: "Cells changed", value: summary.cellsChanged.toLocaleString() },
          ].map(({ label, value }) => (
            <div key={label} className="bg-[var(--surface-primary)] px-4 py-3 text-center">
              <p className="text-[16px] font-bold text-ink">{value}</p>
              <p className="text-[11px] text-ink-muted">{label}</p>
            </div>
          ))}
        </div>

        {/* Columns added / removed */}
        {(columns.added.length > 0 || columns.removed.length > 0) && (
          <div className="border-t border-[var(--line)] px-4 py-3 space-y-2">
            {columns.added.length > 0 && (
              <div>
                <p className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-teal-700">
                  <Plus className="h-3.5 w-3.5" />
                  Columns added
                </p>
                <div className="flex flex-wrap gap-1">
                  {columns.added.map((col) => (
                    <Badge
                      key={col}
                      variant="outline"
                      className="text-[10px] border-teal-200 text-teal-700 bg-teal-50/50"
                    >
                      {col}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {columns.removed.length > 0 && (
              <div>
                <p className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-red-600">
                  <Minus className="h-3.5 w-3.5" />
                  Columns removed
                </p>
                <div className="flex flex-wrap gap-1">
                  {columns.removed.map((col) => (
                    <Badge
                      key={col}
                      variant="outline"
                      className="text-[10px] border-red-200 text-red-600 bg-red-50/50"
                    >
                      {col}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Type changes */}
        {columns.typeChanges.length > 0 && (
          <div className="border-t border-[var(--line)] overflow-x-auto">
            <div className="px-4 py-2">
              <p className="text-[12px] font-medium text-ink-muted mb-1.5">Type changes</p>
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--surface-raised)]">
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">Column</th>
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">Before</th>
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">After</th>
                </tr>
              </thead>
              <tbody>
                {columns.typeChanges.map((tc) => (
                  <tr key={tc.column} className="border-t border-[var(--line)]">
                    <td className="px-3 py-1.5 font-mono text-ink-secondary">{tc.column}</td>
                    <td className="px-3 py-1.5 text-red-600">{tc.beforeType}</td>
                    <td className="px-3 py-1.5 text-teal-600">{tc.afterType}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Statistical drift */}
        {statisticalDrift.length > 0 && (
          <div className="border-t border-[var(--line)] overflow-x-auto">
            <div className="px-4 py-2">
              <p className="text-[12px] font-medium text-ink-muted mb-1.5">Statistical drift</p>
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--surface-raised)]">
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">Column</th>
                  <th className="px-3 py-1.5 text-right font-mono font-medium text-ink-muted">Before mean</th>
                  <th className="px-3 py-1.5 text-right font-mono font-medium text-ink-muted">After mean</th>
                  <th className="px-3 py-1.5 text-right font-mono font-medium text-ink-muted">Change</th>
                </tr>
              </thead>
              <tbody>
                {statisticalDrift.map((d) => (
                  <tr key={d.column} className="border-t border-[var(--line)]">
                    <td className="px-3 py-1.5 font-mono text-ink-secondary">{d.column}</td>
                    <td className="px-3 py-1.5 text-right text-ink-secondary">{d.beforeMean.toFixed(2)}</td>
                    <td className="px-3 py-1.5 text-right text-ink-secondary">{d.afterMean.toFixed(2)}</td>
                    <td className="px-3 py-1.5 text-right font-medium">
                      <span className={d.pctChange > 0 ? "text-teal-600" : d.pctChange < 0 ? "text-red-600" : "text-ink-muted"}>
                        {d.pctChange > 0 ? "+" : ""}{d.pctChange.toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Sample cell changes */}
        {sampleChanges.length > 0 && (
          <div className="border-t border-[var(--line)] overflow-x-auto">
            <div className="px-4 py-2">
              <p className="text-[12px] font-medium text-ink-muted mb-1.5">Sample changes</p>
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--surface-raised)]">
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">Row</th>
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">Column</th>
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">Before</th>
                  <th className="px-3 py-1.5 text-center font-mono font-medium text-ink-muted" />
                  <th className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">After</th>
                </tr>
              </thead>
              <tbody>
                {sampleChanges.map((change, idx) => (
                  <tr key={idx} className="border-t border-[var(--line)]">
                    <td className="px-3 py-1.5 text-ink-muted">{change.row}</td>
                    <td className="px-3 py-1.5 font-mono text-ink-secondary">{change.column}</td>
                    <td className="px-3 py-1.5 text-red-600 bg-red-50/30 truncate max-w-[120px]">
                      {String(change.before ?? "")}
                    </td>
                    <td className="px-1.5 py-1.5 text-center text-ink-muted">
                      <ArrowRight className="inline h-3 w-3" />
                    </td>
                    <td className="px-3 py-1.5 text-teal-600 bg-teal-50/30 truncate max-w-[120px]">
                      {String(change.after ?? "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
