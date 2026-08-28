import { useState } from "react";
import { ChevronDown, ChevronRight, Copy, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { allAssumptions } from "@/lib/analysis-assumptions";
import { formatStatistic } from "@/lib/analysis-format";
import { AssumptionList, AssumptionWarning } from "./AnalysisAssumptions";
import { AnalysisCodeExport } from "./AnalysisCodeExport";
import type { AnalysisMethodsPayload, AnalysisOperationRecord } from "@/types";

interface Props {
  payload: AnalysisMethodsPayload;
}

/** Format a statistic for display without pretending to precision it lacks. */
const formatNumber = formatStatistic;

function OperationBlock({ operation }: { operation: AnalysisOperationRecord }) {
  const stats = operation.statistics ?? {};
  const effect = stats.effect_size;
  const ci = stats.confidence_interval;
  const assumptions = stats.assumptions ?? [];

  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-[13px] font-semibold text-ink">
          {operation.label}
        </span>
        <code className="rounded bg-[var(--surface-raised)] px-1.5 py-0.5 text-[11px] text-ink-muted">
          {operation.op}
        </code>
        <span className="text-[12px] text-ink-muted">
          n&nbsp;=&nbsp;{operation.n}
          {operation.n_excluded > 0
            ? ` (${operation.n_excluded} excluded)`
            : ""}
        </span>
      </div>

      {stats.test ? (
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-muted">
          {stats.test}
          {stats.statistic !== undefined && stats.statistic !== null
            ? ` · statistic ${formatNumber(stats.statistic)}`
            : ""}
          {stats.p_value !== undefined && stats.p_value !== null
            ? ` · p ${formatNumber(stats.p_value)}`
            : ""}
        </p>
      ) : null}

      {effect?.value !== undefined && effect?.value !== null ? (
        <p className="mt-1 text-[12px] text-ink-muted">
          {effect.name} = {formatNumber(effect.value)}
          {effect.magnitude ? (
            <span className="ml-1.5 rounded-full border border-[var(--line)] px-1.5 py-0.5 text-[11px]">
              {effect.magnitude}
            </span>
          ) : null}
        </p>
      ) : null}

      {ci?.low !== undefined && ci?.low !== null ? (
        <p className="mt-1 text-[12px] text-ink-muted">
          {Math.round((ci.level ?? 0.95) * 100)}% CI for{" "}
          {ci.of ?? "the estimate"}: [{formatNumber(ci.low)},{" "}
          {formatNumber(ci.high)}]
        </p>
      ) : null}

      <AssumptionList assumptions={assumptions} className="mt-2" />
    </div>
  );
}

/**
 * The record behind an analysis: what ran, over how many rows, under which
 * assumptions, with which library versions.
 *
 * Collapsed by default — most turns do not need it open — but present on every
 * computed answer, because a figure a reader cannot trace is a figure they have
 * to take on faith.
 */
export function AnalysisMethodsCard({ payload }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const {
    dataset,
    operations,
    environment,
    multipleComparisons,
    methodsNote,
    code,
  } = payload;
  // Surfaced on the collapsed header: a violated assumption that only appears
  // once the card is opened is one most readers will never see.
  const checks = allAssumptions(operations);

  const copyNote = async () => {
    try {
      await navigator.clipboard.writeText(methodsNote);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied; the note stays readable on screen.
      setCopied(false);
    }
  };

  return (
    <div className="my-2 max-w-[85%]">
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm">
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          aria-expanded={expanded}
          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-100 hover:bg-[var(--surface-raised)]"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-600">
            <FlaskConical className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Methods</p>
            <p className="truncate text-[12px] text-ink-muted">
              {operations.length} operation{operations.length === 1 ? "" : "s"}{" "}
              over {dataset.rows.toLocaleString()} rows
              {dataset.filename ? ` of ${dataset.filename}` : ""}
            </p>
            <AssumptionWarning assumptions={checks} className="mt-0.5" />
          </div>
          {expanded ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-ink-muted" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-ink-muted" />
          )}
        </button>

        {expanded ? (
          <div className="border-t border-[var(--line)]">
            {/* Deliberately unanimated. The reader opened this disclosure to
                read it, so a staggered entrance buys nothing — and content that
                is transparent until an animation settles renders as an empty
                card whenever the frame clock is throttled. */}
            <div className="divide-y divide-[var(--line)]">
              {operations.map((operation) => (
                <OperationBlock key={operation.index} operation={operation} />
              ))}
            </div>

            {multipleComparisons ? (
              <div className="border-t border-[var(--line)] bg-amber-50/40 px-4 py-3">
                <p className="text-[12px] font-medium text-ink">
                  {multipleComparisons.n_tests} tests were run against this
                  dataset
                </p>
                <p className="mt-0.5 text-[12px] text-ink-muted">
                  P-values adjusted by {multipleComparisons.method}, which
                  controls the {multipleComparisons.controls}.
                </p>
                <ul className="mt-1.5 space-y-0.5">
                  {multipleComparisons.tests.map((test) => (
                    <li key={test.label} className="text-[12px] text-ink-muted">
                      {test.label}: p {formatNumber(test.p_value)} → adjusted{" "}
                      {formatNumber(test.p_value_adjusted)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--line)] px-4 py-3">
              <p className="text-[11px] leading-relaxed text-ink-muted">
                Computed by deterministic code from the uploaded file — no value
                here was produced by a language model. Python{" "}
                {environment.python}, pandas {environment.pandas}, numpy{" "}
                {environment.numpy}, scipy {environment.scipy}.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={copyNote}
                className="h-7 gap-1.5 text-[12px]"
              >
                <Copy className="h-3 w-3" />
                {copied ? "Copied" : "Copy methods note"}
              </Button>
            </div>

            {/* Beside the methods note, because they make the same claim: the
                note says the figures were computed deterministically, and the
                script is how a reader checks that for themselves. */}
            <AnalysisCodeExport scripts={code} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
