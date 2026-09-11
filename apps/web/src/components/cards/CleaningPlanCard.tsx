import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, BookMarked, ClipboardList, RotateCcw } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { staggerContainer } from "@/lib/motion";
import { getOperationCatalog, validatePlan } from "@/lib/cleaning-api";
import {
  blankStep,
  insertStep,
  issuesForStep,
  moveStep,
  removeStep,
  setStepParam,
  toApiSteps,
  toEditableSteps,
  toggleStep,
  updateStep,
  validateSteps,
  type EditableStep,
  type OperationCatalog,
  type OperationSpec,
  type PlanIssue,
} from "@/lib/plan-editor";
import { AddStepPicker } from "./AddStepPicker";
import { PlanStepRow } from "./PlanStepRow";
import type { CleaningPlanPayload } from "@/types";

interface Props {
  payload: CleaningPlanPayload;
  messageId?: string;
  onAction?: (action: string, data?: unknown) => void;
}

/**
 * The gate between a proposed cleaning plan and the user's data.
 *
 * Nothing here runs until a person presses Apply. Until then every step can be
 * excluded, retargeted at a different column, have its parameters retyped,
 * moved earlier or later, deleted, or joined by a step the planner never
 * suggested. The plan that runs is the one on screen at that moment, not the
 * one the model produced.
 */
export function CleaningPlanCard({ payload, messageId, onAction }: Props) {
  const { summary, datasetId, columns = [], recipeId, recipeName } = payload;

  const [steps, setSteps] = useState<EditableStep[]>(() => toEditableSteps(payload.steps));
  const [expandedUid, setExpandedUid] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<OperationCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [serverIssues, setServerIssues] = useState<readonly PlanIssue[]>([]);
  const [checking, setChecking] = useState(false);
  // Seeded from the payload so an already-applied plan stays applied across a
  // remount (switching sessions away and back) instead of becoming re-applyable.
  const [applied, setApplied] = useState(payload.applied ?? false);

  const proposed = useMemo(() => toEditableSteps(payload.steps), [payload.steps]);

  useEffect(() => {
    let cancelled = false;
    getOperationCatalog()
      .then((loaded) => {
        if (!cancelled) setCatalog(loaded);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // Without the catalogue the card can still apply the plan as proposed —
        // it just cannot offer the editor, so say which half is unavailable.
        setCatalogError(
          error instanceof Error
            ? `Step details are unavailable (${error.message}). You can still include or exclude steps.`
            : "Step details are unavailable. You can still include or exclude steps.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const localIssues = useMemo(
    () => validateSteps(steps, catalog, columns),
    [steps, catalog, columns],
  );
  // Local checks run as the user types; the server's answer arrives on Apply.
  // Showing both, deduplicated by message, keeps the card honest either way.
  const issues = useMemo(() => {
    const seen = new Set(localIssues.map((issue) => `${issue.stepIndex}:${issue.message}`));
    return [
      ...localIssues,
      ...serverIssues.filter((issue) => !seen.has(`${issue.stepIndex}:${issue.message}`)),
    ];
  }, [localIssues, serverIssues]);

  const enabledCount = steps.filter((step) => step.enabled).length;
  const changed =
    steps.length !== proposed.length ||
    steps.some((step, i) => {
      const original = proposed[i];
      return (
        !step.enabled ||
        step.addedByUser ||
        !original ||
        step.operation !== original.operation ||
        step.column !== original.column ||
        step.description !== original.description ||
        JSON.stringify(step.params ?? {}) !== JSON.stringify(original.params ?? {})
      );
    });

  const edit = useCallback((mutate: (current: EditableStep[]) => EditableStep[]) => {
    // Any structural change can invalidate the server's last answer.
    setServerIssues([]);
    setSteps((current) => mutate(current));
  }, []);

  const handleAdd = (spec: OperationSpec) => {
    const step = blankStep(spec);
    edit((current) => insertStep(current, step));
    setExpandedUid(step.uid);
  };

  const handleReset = () => {
    setServerIssues([]);
    setSteps(toEditableSteps(payload.steps));
    setExpandedUid(null);
  };

  const handleApply = async () => {
    if (applied || enabledCount === 0 || issues.length > 0) return;

    const apiSteps = toApiSteps(steps);

    // Ask the server before locking the card: a plan that only fails at
    // dispatch would leave the card saying "Applying…" over nothing.
    setChecking(true);
    try {
      const result = await validatePlan(datasetId, apiSteps);
      if (!result.valid) {
        setServerIssues(result.issues);
        return;
      }
    } catch {
      // The check itself failed (offline, API down). Applying will surface the
      // same problem with a proper error card, so don't block on it.
    } finally {
      setChecking(false);
    }

    setApplied(true);
    onAction?.("apply_cleaning", {
      datasetId,
      steps: apiSteps,
      messageId,
      recipeId,
      edited: changed,
    });
  };

  const applyLabel = () => {
    if (applied) return "Applied";
    if (checking) return "Checking…";
    return `Apply ${enabledCount} step${enabledCount !== 1 ? "s" : ""}`;
  };

  return (
    <div className="my-2 max-w-[85%]">
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-brand-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
            {recipeName ? <BookMarked className="h-4 w-4" /> : <ClipboardList className="h-4 w-4" />}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold text-ink">
              {recipeName ? `Recipe: ${recipeName}` : "Cleaning Plan"}
            </p>
            <p className="text-[12px] text-ink-muted">
              {steps.length} step{steps.length !== 1 ? "s" : ""} —{" "}
              {applied ? "applied" : "nothing runs until you approve it"}
            </p>
          </div>
          {changed && !applied && (
            <button
              type="button"
              onClick={handleReset}
              className="flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-[11px] text-ink-muted transition-colors hover:bg-[var(--surface-inset)] hover:text-ink"
            >
              <RotateCcw className="h-3 w-3" />
              Reset
            </button>
          )}
        </div>

        {summary && (
          <div className="border-b border-[var(--line)] px-4 py-3">
            <p className="text-[13px] leading-relaxed text-ink-secondary">{summary}</p>
          </div>
        )}

        {catalogError && (
          <div className="flex items-start gap-2 border-b border-[var(--line)] bg-amber-50/60 px-4 py-2.5 text-[12px] text-amber-800">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{catalogError}</span>
          </div>
        )}

        {/* Steps */}
        <motion.div
          className="divide-y divide-[var(--line)]"
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
        >
          {steps.map((step, index) => (
            <PlanStepRow
              key={step.uid}
              step={step}
              spec={catalog?.operations.find((op) => op.name === step.operation)}
              index={index}
              isFirst={index === 0}
              isLast={index === steps.length - 1}
              issues={issuesForStep(issues, index)}
              columns={columns}
              expanded={expandedUid === step.uid}
              locked={applied}
              onToggle={() => edit((current) => toggleStep(current, step.uid))}
              onExpand={() => setExpandedUid(expandedUid === step.uid ? null : step.uid)}
              onMove={(direction) => edit((current) => moveStep(current, step.uid, direction))}
              onRemove={() => {
                edit((current) => removeStep(current, step.uid));
                if (expandedUid === step.uid) setExpandedUid(null);
              }}
              onColumnChange={(column) =>
                edit((current) => updateStep(current, step.uid, { column }))
              }
              onParamChange={(name, value) =>
                edit((current) => setStepParam(current, step.uid, name, value))
              }
              onDescriptionChange={(description) =>
                edit((current) => updateStep(current, step.uid, { description }))
              }
            />
          ))}
        </motion.div>

        {steps.length === 0 && (
          <p className="px-4 py-4 text-[12px] text-ink-muted">
            No steps left. Add one below, or reset to the proposed plan.
          </p>
        )}

        {/* Add a step */}
        {!applied && (
          <div className="border-t border-[var(--line)] px-4 py-3">
            <AddStepPicker catalog={catalog} onAdd={handleAdd} />
          </div>
        )}

        {/* Apply footer */}
        <div className="flex items-center justify-between gap-2 border-t border-[var(--line)] bg-[var(--surface-primary)] px-4 py-3">
          <p className="text-[12px] text-ink-muted">
            {applied
              ? "Applying selected steps…"
              : issues.length > 0
                ? `${issues.length} thing${issues.length !== 1 ? "s" : ""} to fix first`
                : `${enabledCount} of ${steps.length} selected${changed ? " · edited" : ""}`}
          </p>
          <Button
            size="sm"
            disabled={applied || checking || enabledCount === 0 || issues.length > 0}
            onClick={() => void handleApply()}
            className="bg-brand-600 text-white transition-all duration-150 hover:bg-brand-700 active:scale-[0.98]"
          >
            {applyLabel()}
          </Button>
        </div>
      </div>
    </div>
  );
}
