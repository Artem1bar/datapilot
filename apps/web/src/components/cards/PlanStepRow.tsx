import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Pencil,
  Trash2,
} from "lucide-react";
import { motion } from "framer-motion";
import { staggerItem } from "@/lib/motion";
import { PlanStepEditor } from "./PlanStepEditor";
import { describeParams } from "@/lib/plan-editor";
import type { EditableStep, OperationSpec, PlanIssue } from "@/lib/plan-editor";

interface Props {
  step: EditableStep;
  spec: OperationSpec | undefined;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  issues: readonly PlanIssue[];
  columns: readonly string[];
  expanded: boolean;
  /** Read-only once the plan has been applied. */
  locked: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
  onColumnChange: (column: string | null) => void;
  onParamChange: (name: string, value: unknown) => void;
  onDescriptionChange: (description: string) => void;
}

const ICON_BUTTON =
  "flex h-5 w-5 items-center justify-center rounded text-ink-muted transition-colors " +
  "hover:bg-[var(--surface-inset)] hover:text-ink disabled:cursor-default disabled:opacity-30";

export function PlanStepRow({
  step,
  spec,
  index,
  isFirst,
  isLast,
  issues,
  columns,
  expanded,
  locked,
  onToggle,
  onExpand,
  onMove,
  onRemove,
  onColumnChange,
  onParamChange,
  onDescriptionChange,
}: Props) {
  const included = step.enabled;
  const hasIssues = issues.length > 0;
  const values = describeParams(step, spec);

  return (
    <motion.div variants={staggerItem} className="px-4 py-3">
      <div className="flex items-start gap-3">
        <button
          type="button"
          disabled={locked}
          onClick={onToggle}
          aria-pressed={included}
          aria-label={included ? "Exclude this step" : "Include this step"}
          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
            included
              ? "border-brand-600 bg-brand-600 text-white"
              : "border-[var(--line)] bg-transparent text-transparent"
          } ${locked ? "cursor-default opacity-70" : "hover:border-brand-500"}`}
        >
          <Check className="h-3 w-3" />
        </button>

        <div className={`min-w-0 flex-1 ${included ? "" : "opacity-50"}`}>
          <div className="flex items-start gap-2">
            <p className="min-w-0 flex-1 text-[13px] font-medium text-ink">{step.description}</p>

            {!locked && (
              <div className="flex shrink-0 items-center gap-0.5">
                <button
                  type="button"
                  className={ICON_BUTTON}
                  disabled={isFirst}
                  onClick={() => onMove(-1)}
                  aria-label={`Move step ${index + 1} earlier`}
                >
                  <ChevronUp className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className={ICON_BUTTON}
                  disabled={isLast}
                  onClick={() => onMove(1)}
                  aria-label={`Move step ${index + 1} later`}
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className={ICON_BUTTON}
                  onClick={onExpand}
                  aria-expanded={expanded}
                  aria-label={`${expanded ? "Hide" : "Edit"} step ${index + 1} settings`}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className={`${ICON_BUTTON} hover:text-rose-600`}
                  onClick={onRemove}
                  aria-label={`Delete step ${index + 1}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>

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
            {values.map((entry) => (
              <span
                key={entry.label}
                className="max-w-[16rem] truncate rounded bg-[var(--surface-inset)] px-1.5 py-0.5"
                title={`${entry.label}: ${entry.value}`}
              >
                {entry.label}: <span className="font-mono">{entry.value}</span>
              </span>
            ))}
            {spec?.destructive && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
                removes data
              </span>
            )}
            {step.addedByUser && (
              <span className="rounded bg-teal-100 px-1.5 py-0.5 text-teal-700">you added</span>
            )}
            {step.edited && (
              <span className="rounded bg-brand-100 px-1.5 py-0.5 text-brand-700">edited</span>
            )}
            {step.confidence != null && !step.addedByUser && (
              <span className="ml-auto tabular-nums">
                {Math.round(step.confidence * 100)}% confidence
              </span>
            )}
          </div>

          {hasIssues && (
            <ul className="mt-1.5 space-y-0.5">
              {issues.map((issue, i) => (
                <li key={i} className="flex items-start gap-1.5 text-[11px] text-rose-600">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          )}

          {expanded && spec && !locked && (
            <PlanStepEditor
              step={step}
              spec={spec}
              columns={columns}
              onColumnChange={onColumnChange}
              onParamChange={onParamChange}
              onDescriptionChange={onDescriptionChange}
            />
          )}
        </div>
      </div>
    </motion.div>
  );
}
