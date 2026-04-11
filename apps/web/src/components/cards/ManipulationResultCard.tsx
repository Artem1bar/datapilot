import { motion } from "framer-motion";
import { Check, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ManipulationResultPayload } from "@/types";

interface Props {
  payload: ManipulationResultPayload;
  onAction?: (action: string, data?: unknown) => void;
}

export function ManipulationResultCard({ payload, onAction }: Props) {
  const { snapshotId, newRowCount, newColCount, columnsAdded, columnsRemoved, columnsRenamed, sampleRows } = payload;

  const changes: string[] = [];
  if (columnsRemoved.length) changes.push(`Deleted ${columnsRemoved.length} column(s)`);
  if (columnsAdded.length) changes.push(`Added ${columnsAdded.length} column(s)`);
  if (Object.keys(columnsRenamed).length) changes.push(`Renamed ${Object.keys(columnsRenamed).length} column(s)`);

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-teal-200 bg-teal-50/30 shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-teal-200 bg-teal-50 px-4 py-3">
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring", stiffness: 400, damping: 15 }}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-100 text-teal-600"
          >
            <Check className="h-4 w-4" />
          </motion.div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Edit Applied</p>
            <p className="text-[12px] text-teal-700">
              {changes.join(", ") || "Changes applied successfully"}
            </p>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-px bg-teal-200/50">
          {[
            { label: "Rows", value: newRowCount.toLocaleString() },
            { label: "Columns", value: newColCount.toLocaleString() },
          ].map(({ label, value }) => (
            <div key={label} className="bg-[var(--surface-primary)] px-4 py-3 text-center">
              <p className="text-[18px] font-bold text-ink">{value}</p>
              <p className="text-[11px] text-ink-muted">{label}</p>
            </div>
          ))}
        </div>

        {/* Sample rows */}
        {sampleRows.length > 0 && (
          <div className="border-t border-teal-200 overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--surface-raised)]">
                  {Object.keys(sampleRows[0]).slice(0, 6).map(col => (
                    <th key={col} className="px-3 py-1.5 text-left font-mono font-medium text-ink-muted">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sampleRows.slice(0, 3).map((row, i) => (
                  <tr key={i} className="border-t border-[var(--line)]">
                    {Object.keys(sampleRows[0]).slice(0, 6).map(col => (
                      <td key={col} className="px-3 py-1.5 text-ink-secondary truncate max-w-[120px]">
                        {String(row[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Undo */}
        {snapshotId && (
          <div className="flex gap-2 border-t border-teal-200 bg-[var(--surface-primary)] px-4 py-3">
            <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onAction?.("undo_manipulation", snapshotId)}
              >
                <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                Undo
              </Button>
            </motion.div>
          </div>
        )}
      </div>
    </div>
  );
}
