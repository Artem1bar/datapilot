import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Check, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { ManipulationPreviewPayload } from "@/types";

type Operation = ManipulationPreviewPayload["operations"][number];

interface Props {
  payload: ManipulationPreviewPayload;
  onAction?: (action: string, data?: unknown) => void;
}

interface PreviewState {
  readonly previewBefore: ReadonlyArray<Record<string, unknown>>;
  readonly previewAfter: ReadonlyArray<Record<string, unknown>>;
  readonly warnings: readonly string[];
  readonly affectedRowCount: number;
}

/**
 * The gate between a parsed edit command and the user's data.
 *
 * Each operation the AI read out of the command can be excluded on its own. The
 * before/after table is then re-computed server-side for exactly what is still
 * selected — showing the result of an operation the user just excluded would be
 * worse than showing nothing.
 */
export function ManipulationPreviewCard({ payload, onAction }: Props) {
  const { command, operations, datasetId } = payload;

  const [included, setIncluded] = useState<boolean[]>(() => operations.map(() => true));
  const [applied, setApplied] = useState(payload.applied ?? false);
  const [preview, setPreview] = useState<PreviewState>({
    previewBefore: payload.previewBefore,
    previewAfter: payload.previewAfter,
    warnings: payload.warnings,
    affectedRowCount: payload.affectedRowCount,
  });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const selected: Operation[] = operations.filter((_, i) => included[i]);
  const selectedCount = selected.length;
  const isFullSet = selectedCount === operations.length;

  // Re-preview whenever the selection narrows. The full set already arrived
  // with the payload, so going back to it needs no request.
  const requestId = useRef(0);
  const selectionKey = included.join(",");
  useEffect(() => {
    if (applied || isFullSet || selectedCount === 0 || !datasetId) return;

    const id = ++requestId.current;
    setRefreshing(true);
    setRefreshError(null);

    api
      .post(`manipulation/${datasetId}/preview`, {
        json: { operations: selected.map((op) => ({ op_type: op.opType, params: op.params, description: op.description })) },
        timeout: 60_000,
      })
      .json<{
        preview_before: Record<string, unknown>[];
        preview_after: Record<string, unknown>[];
        warnings: string[];
        affected_row_count: number;
      }>()
      .then((fresh) => {
        if (id !== requestId.current) return; // a newer selection won
        setPreview({
          previewBefore: fresh.preview_before,
          previewAfter: fresh.preview_after,
          warnings: fresh.warnings,
          affectedRowCount: fresh.affected_row_count,
        });
      })
      .catch((error: unknown) => {
        if (id !== requestId.current) return;
        setRefreshError(
          error instanceof Error
            ? `Couldn't refresh the preview (${error.message}). The table below still shows all operations.`
            : "Couldn't refresh the preview. The table below still shows all operations.",
        );
      })
      .finally(() => {
        if (id === requestId.current) setRefreshing(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the selection; `selected` is derived from it
  }, [selectionKey, applied, datasetId]);

  // Back to the full set: restore the preview the payload came with.
  useEffect(() => {
    if (!isFullSet) return;
    requestId.current += 1;
    setRefreshError(null);
    setRefreshing(false);
    setPreview({
      previewBefore: payload.previewBefore,
      previewAfter: payload.previewAfter,
      warnings: payload.warnings,
      affectedRowCount: payload.affectedRowCount,
    });
  }, [isFullSet, payload]);

  const toggle = (index: number) => {
    if (applied) return;
    setIncluded((prev) => prev.map((value, i) => (i === index ? !value : value)));
  };

  const handleApply = () => {
    if (applied || selectedCount === 0) return;
    setApplied(true);
    onAction?.("apply_manipulation", selected);
  };

  const beforeCols = preview.previewBefore.length > 0 ? Object.keys(preview.previewBefore[0]) : [];
  const afterCols = preview.previewAfter.length > 0 ? Object.keys(preview.previewAfter[0]) : [];
  const addedCols = new Set(afterCols.filter((c) => !beforeCols.includes(c)));

  return (
    <div className="my-2 max-w-[85%]">
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm">
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

        {/* Operations, each includable on its own */}
        <motion.div
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
          className="divide-y divide-[var(--line)]"
        >
          {operations.map((op, idx) => {
            const isOn = included[idx];
            return (
              <motion.div
                key={idx}
                variants={staggerItem}
                className="flex items-start gap-3 px-4 py-2.5"
              >
                <button
                  type="button"
                  disabled={applied}
                  onClick={() => toggle(idx)}
                  aria-pressed={isOn}
                  aria-label={isOn ? "Exclude this change" : "Include this change"}
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
                    isOn
                      ? "border-brand-600 bg-brand-600 text-white"
                      : "border-[var(--line)] bg-transparent text-transparent"
                  } ${applied ? "cursor-default opacity-70" : "hover:border-brand-500"}`}
                >
                  <Check className="h-3 w-3" />
                </button>
                <div className={`min-w-0 flex-1 ${isOn ? "" : "opacity-50"}`}>
                  <p className="text-[13px] text-ink">{op.description}</p>
                  <span className="mt-0.5 inline-block rounded bg-[var(--surface-inset)] px-1.5 py-0.5 font-mono text-[10px] text-ink-muted">
                    {op.opType}
                  </span>
                </div>
              </motion.div>
            );
          })}
        </motion.div>

        {/* Warnings */}
        {preview.warnings.length > 0 && (
          <div className="border-t border-[var(--line)] bg-amber-50/50 px-4 py-2.5">
            {preview.warnings.map((warning, i) => (
              <div key={i} className="flex items-center gap-2 text-[12px] text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>{warning}</span>
              </div>
            ))}
          </div>
        )}

        {refreshError && (
          <div className="flex items-start gap-2 border-t border-[var(--line)] bg-amber-50/60 px-4 py-2.5 text-[12px] text-amber-800">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{refreshError}</span>
          </div>
        )}

        {/* Before/After preview table */}
        {preview.previewAfter.length > 0 && (
          <div className="overflow-x-auto border-t border-[var(--line)]">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--surface-raised)]">
                  {afterCols.slice(0, 8).map((col) => (
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
                {preview.previewAfter.slice(0, 3).map((row, i) => (
                  <tr key={i} className="border-t border-[var(--line)]">
                    {afterCols.slice(0, 8).map((col) => (
                      <td
                        key={col}
                        className="max-w-[120px] truncate px-3 py-1.5 text-ink-secondary"
                      >
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
        <div className="flex items-center gap-2 border-t border-[var(--line)] bg-[var(--surface-primary)] px-4 py-3">
          <p className="min-w-0 flex-1 text-[12px] text-ink-muted">
            {applied
              ? "Applying selected changes…"
              : refreshing
                ? "Updating the preview…"
                : `${selectedCount} of ${operations.length} selected`}
          </p>
          <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
            <Button
              size="sm"
              disabled={applied || selectedCount === 0 || refreshing}
              className="bg-brand-600 text-white hover:bg-brand-700"
              onClick={handleApply}
            >
              <Check className="mr-1.5 h-3.5 w-3.5" />
              {applied
                ? "Applied"
                : `Apply ${selectedCount} change${selectedCount !== 1 ? "s" : ""}`}
            </Button>
          </motion.div>
          {!applied && (
            <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
              <Button variant="outline" size="sm" onClick={() => onAction?.("cancel_manipulation")}>
                <X className="mr-1.5 h-3.5 w-3.5" />
                Cancel
              </Button>
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
