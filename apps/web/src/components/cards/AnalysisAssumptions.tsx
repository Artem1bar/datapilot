import { Check, Minus, TriangleAlert } from "lucide-react";
import {
  assumptionState,
  assumptionTally,
  byWorstFirst,
} from "@/lib/analysis-assumptions";
import type { AnalysisAssumption } from "@/types";

/**
 * Assumption state is three-valued, and the third value matters: "could not be
 * evaluated" is a different claim from "this is fine", and collapsing them
 * would let an untested assumption read as a satisfied one.
 *
 * Each state is carried by an icon, a colour and a word. Colour alone would put
 * the whole distinction out of reach of a reader who cannot see it, and this is
 * the one thing on the card that must not be missed.
 */
const STATES = {
  passed: {
    label: "passed",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
    Icon: Check,
  },
  failed: {
    label: "failed",
    tone: "border-amber-300 bg-amber-50 text-amber-800",
    Icon: TriangleAlert,
  },
  unevaluated: {
    label: "not evaluated",
    tone: "border-[var(--line)] bg-[var(--surface-raised)] text-ink-muted",
    Icon: Minus,
  },
} as const;

export function AssumptionChip({
  assumption,
}: {
  assumption: AnalysisAssumption;
}) {
  const { passed, name, detail } = assumption;
  const { tone, label, Icon } = STATES[assumptionState(passed)];

  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-[12px] ${tone}`}
    >
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="font-medium">{name}</span>
        {detail ? <span className="opacity-80"> — {detail}</span> : null}
      </span>
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide opacity-70">
        {label}
      </span>
    </div>
  );
}

/** Every assumption check on one operation, worst first. */
export function AssumptionList({
  assumptions,
  className = "",
}: {
  assumptions: readonly AnalysisAssumption[];
  className?: string;
}) {
  if (assumptions.length === 0) return null;

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      {byWorstFirst(assumptions).map((assumption) => (
        <AssumptionChip key={assumption.name} assumption={assumption} />
      ))}
    </div>
  );
}

/**
 * A one-line verdict over a set of checks, for a surface that starts collapsed.
 *
 * Renders nothing when everything passed — a banner that is always there is a
 * banner nobody reads — but a failure is stated up front, so seeing it does not
 * depend on the reader opening a disclosure first.
 */
export function AssumptionWarning({
  assumptions,
  className = "",
}: {
  assumptions: readonly AnalysisAssumption[];
  className?: string;
}) {
  const { failed, unevaluated } = assumptionTally(assumptions);
  if (failed === 0 && unevaluated === 0) return null;

  const parts = [
    failed > 0 ? `${failed} assumption${failed === 1 ? "" : "s"} failed` : null,
    unevaluated > 0 ? `${unevaluated} could not be evaluated` : null,
  ].filter(Boolean);

  return (
    <p
      className={`flex items-center gap-1.5 text-[12px] ${
        failed > 0 ? "font-medium text-amber-800" : "text-ink-muted"
      } ${className}`}
    >
      {failed > 0 ? (
        <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : null}
      {parts.join(" · ")}
    </p>
  );
}
