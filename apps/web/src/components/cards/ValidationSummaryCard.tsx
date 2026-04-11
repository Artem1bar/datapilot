import { ShieldCheck, Check, X } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { ValidationSummaryPayload } from "@/types";

interface Props {
  payload: ValidationSummaryPayload;
}

export function ValidationSummaryCard({ payload }: Props) {
  const { results, overallPassed } = payload;
  const passedCount = results.filter((r) => r.passed).length;

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div
          className={cn(
            "flex items-center gap-3 border-b border-[var(--line)] px-4 py-3",
            overallPassed ? "bg-teal-50/50" : "bg-amber-50/50",
          )}
        >
          <div
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-lg",
              overallPassed ? "bg-teal-100 text-teal-600" : "bg-amber-100 text-amber-600",
            )}
          >
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-ink">Validation</p>
            <p className="text-[12px] text-ink-muted">
              {passedCount}/{results.length} checks passed
            </p>
          </div>
        </div>

        {/* Results - staggered */}
        <motion.div
          className="divide-y divide-[var(--line)]"
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
        >
          {results.map((result, idx) => (
            <motion.div key={idx} variants={staggerItem} className="flex items-start gap-3 px-4 py-2.5">
              <div
                className={cn(
                  "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                  result.passed
                    ? "bg-teal-100 text-teal-600"
                    : "bg-coral-100 text-coral-600",
                )}
              >
                {result.passed ? (
                  <Check className="h-3 w-3" />
                ) : (
                  <X className="h-3 w-3" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] text-ink">
                  <span className="font-mono text-[11px] text-ink-muted mr-1.5">#{idx + 1}</span>
                  {result.stepDescription}
                </p>
                {result.detail && (
                  <p className="mt-0.5 text-[11px] text-ink-muted">{result.detail}</p>
                )}
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </div>
  );
}
