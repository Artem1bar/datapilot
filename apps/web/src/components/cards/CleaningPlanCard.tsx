import { ClipboardList, ChevronRight } from "lucide-react";
import { motion } from "framer-motion";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { CleaningPlanPayload } from "@/types";

interface Props {
  payload: CleaningPlanPayload;
  onAction?: (action: string, data?: unknown) => void;
}

export function CleaningPlanCard({ payload }: Props) {
  const { summary, steps } = payload;

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
            <p className="text-[12px] text-ink-muted">{steps.length} steps</p>
          </div>
        </div>

        {/* Summary */}
        {summary && (
          <div className="border-b border-[var(--line)] px-4 py-3">
            <p className="text-[13px] leading-relaxed text-ink-secondary">{summary}</p>
          </div>
        )}

        {/* Steps - staggered */}
        <motion.div
          className="divide-y divide-[var(--line)]"
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
        >
          {steps.map((step, idx) => (
            <motion.div key={idx} variants={staggerItem} className="flex items-start gap-3 px-4 py-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[11px] font-bold text-brand-600">
                {idx + 1}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-ink">{step.description}</p>
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
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </div>
  );
}
