import { lazy, Suspense } from "react";
import { Sigma } from "lucide-react";
import { AssumptionList } from "./AnalysisAssumptions";
import { AnalysisCoefficientTable } from "./AnalysisCoefficientTable";
import { AnalysisWeightedEstimate } from "./AnalysisWeightedEstimate";
import type { AnalysisResultBlock, AnalysisResultsPayload } from "@/types";

// recharts is ~800 kB unminified and only a forecast needs it, so it stays out
// of the initial bundle — the same treatment ChartPanel gives ChartRenderer.
const AnalysisForecastChart = lazy(() =>
  import("./AnalysisForecastChart").then((m) => ({
    default: m.AnalysisForecastChart,
  })),
);

/**
 * The statistics behind an answer, rendered rather than tabulated.
 *
 * This card exists because the generic table contract cannot carry a
 * regression: `columns` and `rows` will happily render a coefficient beside a
 * standard error beside a p-value in a grid with no indication of which is
 * which, no baseline for a categorical, and no interval. What is true of a
 * regression is true of a forecast and of a weighted estimate.
 *
 * Assumption checks are rendered here without a disclosure. The scope document
 * calls surfacing them the line between a statistics tool and a plausible-looking
 * one, and a check a reader has to click to find is a check that did not run as
 * far as they are concerned.
 */

interface Props {
  payload: AnalysisResultsPayload;
}

function ResultBlock({ block }: { block: AnalysisResultBlock }) {
  return (
    <section className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h3 className="text-[13px] font-semibold text-ink">{block.label}</h3>
        <code className="rounded bg-[var(--surface-raised)] px-1.5 py-0.5 text-[11px] text-ink-muted">
          {block.op}
        </code>
        <span className="text-[12px] text-ink-muted">
          n&nbsp;=&nbsp;{block.n.toLocaleString()}
          {block.nExcluded > 0
            ? ` (${block.nExcluded.toLocaleString()} excluded)`
            : ""}
        </span>
      </div>

      {block.regression ? (
        <AnalysisCoefficientTable view={block.regression} />
      ) : null}

      {/* An ARIMA reports both a coefficient table and a forecast, and both
          name the same model. The second copy of that name is noise, so the
          chart drops its heading when the table above already carried it. */}
      {block.forecast ? (
        <Suspense
          fallback={
            <div className="h-[220px] animate-pulse rounded-lg border border-[var(--line)] bg-[var(--surface-raised)]" />
          }
        >
          <AnalysisForecastChart
            view={
              block.regression
                ? { ...block.forecast, model: null }
                : block.forecast
            }
          />
        </Suspense>
      ) : null}

      {block.weighted ? (
        <AnalysisWeightedEstimate view={block.weighted} />
      ) : null}

      <AssumptionList assumptions={block.assumptions} />

      {block.notes.length > 0 ? (
        <ul className="space-y-1">
          {block.notes.map((note) => (
            <li
              key={note}
              className="text-[11px] leading-relaxed text-ink-muted"
            >
              {note}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function AnalysisResultsCard({ payload }: Props) {
  return (
    <div className="my-2 max-w-[85%]">
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm">
        <div className="flex items-center gap-3 border-b border-[var(--line)] px-4 py-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600">
            <Sigma className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">
              Statistical results
            </p>
            <p className="truncate text-[12px] text-ink-muted">
              {payload.blocks.length} model
              {payload.blocks.length === 1 ? "" : "s"} fitted over the full
              dataset
            </p>
          </div>
        </div>

        <div className="divide-y divide-[var(--line)]">
          {payload.blocks.map((block) => (
            <ResultBlock key={block.index} block={block} />
          ))}
        </div>
      </div>
    </div>
  );
}
