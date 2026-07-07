import { Check, AlertCircle, Loader2 } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useSessionStore } from "@/stores/session-store";
import { pulseRing, spring } from "@/lib/motion";
import type { WorkflowStepStatus } from "@/types";

const stepIcons: Record<WorkflowStepStatus, React.ReactNode> = {
  pending: null,
  active: <Loader2 className="h-3 w-3 animate-spin" />,
  complete: <Check className="h-3 w-3" />,
  error: <AlertCircle className="h-3 w-3" />,
};

const stepColors: Record<WorkflowStepStatus, string> = {
  pending: "bg-[var(--surface-inset)] text-ink-muted border-[var(--line)]",
  active: "bg-brand-600 text-white border-brand-600 shadow-md shadow-brand-600/20",
  complete: "bg-teal-600 text-white border-teal-600",
  error: "bg-coral-600 text-white border-coral-600",
};

const lineColors: Record<WorkflowStepStatus, string> = {
  pending: "bg-[var(--line)]",
  active: "bg-[var(--line)]",
  complete: "bg-teal-600",
  error: "bg-coral-600",
};

interface WorkflowStepperProps {
  steps?: readonly import("@/types").WorkflowStep[];
  filename?: string;
}

export function WorkflowStepper({ steps: propSteps, filename: propFilename }: WorkflowStepperProps = {}) {
  const workflowState = useSessionStore((s) =>
    s.activeSessionId ? s.workflowStateBySession[s.activeSessionId] : undefined,
  );

  const steps = propSteps ?? workflowState?.steps;
  const filename = propFilename ?? workflowState?.datasetFilename;

  if (!steps) return null;

  return (
    <AnimatePresence>
      <motion.div
        className="flex flex-col"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={spring.gentle}
      >
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between">
          {steps.map((step, idx) => (
            <div key={step.id} className="flex flex-1 items-center">
              {/* Step circle */}
              <div className="flex items-center gap-2">
                <div className="relative">
                  {/* Pulse ring for active step */}
                  {step.status === "active" && (
                    <motion.div
                      className="absolute inset-0 rounded-full border-2 border-brand-400"
                      variants={pulseRing}
                      animate="animate"
                    />
                  )}
                  <motion.div
                    className={cn(
                      "flex h-6 w-6 items-center justify-center rounded-full border-2 text-[10px] font-bold",
                      stepColors[step.status],
                    )}
                    layout
                    transition={spring.snappy}
                  >
                    {stepIcons[step.status] ?? (idx + 1)}
                  </motion.div>
                </div>
                <span
                  className={cn(
                    "text-[12px] font-medium transition-colors duration-200",
                    step.status === "active" ? "text-brand-600" :
                    step.status === "complete" ? "text-teal-600" :
                    step.status === "error" ? "text-coral-600" :
                    "text-ink-muted",
                  )}
                >
                  {step.label}
                </span>
              </div>

              {/* Connector line (not after last step) */}
              {idx < steps.length - 1 && (
                <motion.div
                  className={cn(
                    "mx-3 h-0.5 flex-1 rounded-full",
                    lineColors[step.status],
                  )}
                  layout
                  transition={spring.gentle}
                />
              )}
            </div>
          ))}
        </div>

        {/* Dataset context */}
        {filename && (
          <p className="mx-auto mt-1 max-w-3xl text-[11px] text-ink-muted">
            {filename}
          </p>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
