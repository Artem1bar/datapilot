import { Loader2, Check, AlertCircle } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useSmoothValue } from "@/hooks/use-smooth-value";
import type { CleaningProgressPayload } from "@/types";

interface Props {
  payload: CleaningProgressPayload;
}

export function CleaningProgressCard({ payload }: Props) {
  const { progress, status, message } = payload;

  const isComplete = status === "complete";
  const isError = status === "error";

  const smoothProgress = useSmoothValue(progress);

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] p-4 shadow-sm">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
              isComplete ? "bg-teal-100 text-teal-600" :
              isError ? "bg-coral-100 text-coral-600" :
              "bg-brand-100 text-brand-600",
            )}
          >
            {isComplete ? (
              <Check className="h-4 w-4" />
            ) : isError ? (
              <AlertCircle className="h-4 w-4" />
            ) : (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium text-ink">{message}</p>
            <div className="mt-2">
              <div
                className={cn(
                  "h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-inset)]",
                )}
              >
                <motion.div
                  className={cn(
                    "h-full rounded-full",
                    isComplete ? "bg-teal-600" :
                    isError ? "bg-coral-600" :
                    "bg-brand-600",
                  )}
                  style={{ width: smoothProgress.get() + "%" }}
                  animate={{ width: `${progress}%` }}
                  transition={{ type: "spring", stiffness: 200, damping: 25 }}
                />
              </div>
            </div>
            <p className="mt-1 text-[11px] text-ink-muted">{progress}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}
