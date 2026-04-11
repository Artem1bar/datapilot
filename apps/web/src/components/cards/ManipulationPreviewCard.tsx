import { motion } from "framer-motion";
import { Pencil, AlertTriangle, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { ManipulationPreviewPayload } from "@/types";

interface Props {
  payload: ManipulationPreviewPayload;
  onAction?: (action: string, data?: unknown) => void;
}

export function ManipulationPreviewCard({ payload, onAction }: Props) {
  const { command, operations, previewBefore, previewAfter, warnings } = payload;

  // Get column names from before/after
  const beforeCols = previewBefore.length > 0 ? Object.keys(previewBefore[0]) : [];
  const afterCols = previewAfter.length > 0 ? Object.keys(previewAfter[0]) : [];
  const addedCols = new Set(afterCols.filter(c => !beforeCols.includes(c)));

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-brand-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
            <Pencil className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Edit Preview</p>
            <p className="truncate text-[12px] text-ink-muted">&ldquo;{command}&rdquo;</p>
          </div>
        </div>

        {/* Operations */}
        <motion.div
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
          className="divide-y divide-[var(--line)]"
        >
          {operations.map((op, idx) => (
            <motion.div
              key={idx}
              variants={staggerItem}
              className="flex items-start gap-3 px-4 py-2.5"
            >
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[10px] font-bold text-brand-600">
                {idx + 1}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] text-ink">{op.description}</p>
                <span className="mt-0.5 inline-block rounded bg-[var(--surface-inset)] px-1.5 py-0.5 font-mono text-[10px] text-ink-muted">
                  {op.opType}
                </span>
              </div>
            </motion.div>
          ))}
        </motion.div>

        {/* Warnings */}
        {warnings.length > 0 && (
          <div className="border-t border-[var(--line)] bg-amber-50/50 px-4 py-2.5">
            {warnings.map((w, i) => (
              <div key={i} className="flex items-center gap-2 text-[12px] text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>{w}</span>
              </div>
            ))}
          </div>
        )}

        {/* Before/After preview table */}
        {previewAfter.length > 0 && (
          <div className="border-t border-[var(--line)] overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--surface-raised)]">
                  {afterCols.slice(0, 8).map(col => (
                    <th
                      key={col}
                      className={`px-3 py-1.5 text-left font-mono font-medium ${
                        addedCols.has(col) ? "text-teal-600" : "text-ink-muted"
                      }`}
                    >
                      {addedCols.has(col) && "+ "}
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewAfter.slice(0, 3).map((row, i) => (
                  <tr key={i} className="border-t border-[var(--line)]">
                    {afterCols.slice(0, 8).map(col => (
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

        {/* Actions */}
        <div className="flex gap-2 border-t border-[var(--line)] bg-[var(--surface-primary)] px-4 py-3">
          <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
            <Button
              size="sm"
              className="bg-brand-600 text-white hover:bg-brand-700"
              onClick={() => onAction?.("apply_manipulation", payload.operations)}
            >
              <Check className="mr-1.5 h-3.5 w-3.5" />
              Apply Changes
            </Button>
          </motion.div>
          <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onAction?.("cancel_manipulation")}
            >
              <X className="mr-1.5 h-3.5 w-3.5" />
              Cancel
            </Button>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
