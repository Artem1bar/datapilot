import { useState } from "react";
import { ClipboardList, ChevronRight, Check } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { CleaningPlanPayload } from "@/types";

interface Props {
  payload: CleaningPlanPayload;
  onAction?: (action: string, data?: unknown) => void;
}

export function CleaningPlanCard({ payload, onAction }: Props) {
  const { summary, steps, datasetId } = payload;
  const [accepted, setAccepted] = useState<boolean[]>(() => steps.map(() => true));
  const [applied, setApplied] = useState(false);

  const acceptedCount = accepted.filter(Boolean).length;

  const toggle = (idx: number) => {
    if (applied) return;
    setAccepted((prev) => prev.map((v, i) => (i === idx ? !v : v)));
  };

  const handleApply = () => {
    if (applied || acceptedCount === 0) return;
    // Strip UI-only fields; send the plain CleaningStep shape the API expects.
    const selected = steps
      .filter((_, i) => accepted[i])
      .map(({ confidence: _confidence, rationale: _rationale, ...rest }) => rest);
    setApplied(true);
    onAction?.("apply_cleaning", { datasetId, steps: selected });
  };

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-brand-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
            <ClipboardList className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Cleaning Plan</p>
            <p className="text-[12px] text-ink-muted">
              {steps.length} step{steps.length !== 1 ? "s" : ""} — review and apply
            </p>
          </div>
        </div>

        {/* Summary */}
        {summary && (
          <div className="border-b border-[var(--line)] px-4 py-3">
            <p className="text-[13px] leading-relaxed text-ink-secondary">{summary}</p>
          </div>
        )}

        {/* Steps - staggered, each toggleable */}
        <motion.div
          className="divide-y divide-[var(--line)]"
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
        >
          {steps.map((step, idx) => {
            const isOn = accepted[idx];
            return (
              <motion.div key={idx} variants={staggerItem} className="flex items-start gap-3 px-4 py-3">
                <button
                  type="button"
                  disabled={applied}
                  onClick={() => toggle(idx)}
                  aria-pressed={isOn}
                  aria-label={isOn ? "Exclude this step" : "Include this step"}
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
                    isOn
                      ? "border-brand-600 bg-brand-600 text-white"
                      : "border-[var(--line)] bg-transparent text-transparent"
                  } ${applied ? "cursor-default opacity-70" : "hover:border-brand-500"}`}
                >
                  <Check className="h-3 w-3" />
                </button>
                <div className={`min-w-0 flex-1 ${isOn ? "" : "opacity-50"}`}>
                  <p className="text-[13px] font-medium text-ink">{step.description}</p>
                  {step.rationale && (
                    <p className="mt-0.5 text-[12px] leading-relaxed text-ink-muted">{step.rationale}</p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                    <span className="rounded bg-[var(--surface-inset)] px-1.5 py-0.5 font-mono">
                      {step.operation}
                    </span>
                    {step.column && (
                      <>
                        <ChevronRight className="h-3 w-3" />
                        <span className="font-mono">{step.column}</span>
                      </>
                    )}
                    {step.confidence != null && (
                      <span className="ml-auto tabular-nums">
                        {Math.round(step.confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </motion.div>

        {/* Apply footer */}
        <div className="flex items-center justify-between gap-2 border-t border-[var(--line)] bg-[var(--surface-primary)] px-4 py-3">
          <p className="text-[12px] text-ink-muted">
            {applied
              ? "Applying selected steps…"
              : `${acceptedCount} of ${steps.length} selected`}
          </p>
          <Button
            size="sm"
            disabled={applied || acceptedCount === 0}
            onClick={handleApply}
            className="bg-brand-600 text-white hover:bg-brand-700 transition-all duration-150 active:scale-[0.98]"
          >
            {applied
              ? "Applied"
              : `Apply ${acceptedCount} step${acceptedCount !== 1 ? "s" : ""}`}
          </Button>
        </div>
      </div>
    </div>
  );
}
