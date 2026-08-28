import {
  formatInterval,
  formatLevel,
  formatPValue,
  formatStatistic,
  isSignificant,
} from "@/lib/analysis-format";
import type {
  AnalysisCoefficientRow,
  AnalysisRegressionView,
  AnalysisVif,
} from "@/types";

/**
 * A regression table, laid out the way a regression table is read.
 *
 * Three things this deliberately does not do.
 *
 * It does not render a ladder of stars. A wall of asterisks encodes a p-value
 * to one significant figure and then invites the reader to treat 0.049 and
 * 0.00001 as different kinds of finding. One mark at the conventional 5% level
 * is enough to scan by, and the interval beside it says more than any number of
 * stars could.
 *
 * It does not hide the omitted baseline. Each indicator coefficient is a
 * difference from a level that is not in the table unless it is put there, and
 * a coefficient table whose baseline is unnamed cannot be interpreted at all.
 *
 * And it does not print anything for a statistic the backend could not compute.
 * Those arrive as null, and null renders as an em dash — never as zero, and
 * never as the word "null".
 */

interface Props {
  view: AnalysisRegressionView;
}

/** Above this variance inflation factor a coefficient is not separately
 *  identified; the backend uses the same conventional cutoff for its verdict. */
const VIF_LIMIT = 10;

function TermCell({ row }: { row: AnalysisCoefficientRow }) {
  if (row.variable === null) {
    return <span className="font-medium text-ink">{row.term}</span>;
  }
  return (
    <span className="text-ink">
      <span className="text-ink-muted">{row.variable}</span>
      <span className="font-medium"> {row.level}</span>
    </span>
  );
}

function CoefficientRow({
  row,
  showRatio,
  level,
}: {
  row: AnalysisCoefficientRow;
  showRatio: boolean;
  level: string;
}) {
  if (row.isReference) {
    return (
      <tr className="bg-[var(--surface-raised)]/60">
        <td className="px-3 py-1.5">
          <TermCell row={row} />
        </td>
        <td
          className="px-3 py-1.5 text-[11px] italic text-ink-muted"
          colSpan={showRatio ? 5 : 4}
        >
          reference level — every {row.variable} estimate below is a difference
          from this
        </td>
      </tr>
    );
  }

  // One mark, at the conventional level, and only when there is a p-value to
  // decide it. A missing p-value is not evidence of no effect, so an unknown
  // verdict is rendered the same as a negative one — unmarked, not asserted.
  const significant = isSignificant(row.pValue) === true;

  return (
    <tr className={significant ? "bg-sky-50/40" : undefined}>
      <td className="px-3 py-1.5">
        <span className="inline-flex items-center gap-1.5">
          {significant ? (
            <span
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-sky-600"
              title="p < 0.05"
              aria-label="significant at the 5% level"
            />
          ) : (
            <span className="h-1.5 w-1.5 shrink-0" aria-hidden />
          )}
          <TermCell row={row} />
        </span>
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums text-ink">
        {formatStatistic(row.estimate)}
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums text-ink-muted">
        {formatStatistic(row.stdError)}
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums text-ink-muted">
        {formatStatistic(row.statistic)}
      </td>
      <td
        className={`px-3 py-1.5 text-right tabular-nums ${significant ? "font-medium text-ink" : "text-ink-muted"}`}
      >
        {row.pValueIsBound && row.pValue !== null ? "< " : ""}
        {formatPValue(row.pValue)}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-ink-muted">
        {formatInterval(row.ciLow, row.ciHigh)}
        <span className="sr-only"> {level} confidence interval</span>
      </td>
      {showRatio ? (
        <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-ink">
          {formatStatistic(row.ratio?.value)}{" "}
          <span className="text-ink-muted">
            {formatInterval(row.ratio?.low ?? null, row.ratio?.high ?? null, 3)}
          </span>
        </td>
      ) : null}
    </tr>
  );
}

function FitStatistics({ view }: Props) {
  if (view.fit.length === 0) return null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 px-3 py-2 sm:grid-cols-3">
      {view.fit.map((stat) => (
        <div
          key={stat.label}
          className="flex items-baseline justify-between gap-2"
        >
          <dt className="text-[11px] text-ink-muted">{stat.label}</dt>
          <dd className="text-[12px] font-medium tabular-nums text-ink">
            {stat.kind === "integer"
              ? formatStatistic(stat.value, 0)
              : stat.kind === "p_value"
                ? formatPValue(stat.value)
                : formatStatistic(stat.value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Only the regressors whose VIF the backend flagged; the rest are noise. */
function inflatedTerms(vif: readonly AnalysisVif[]): AnalysisVif[] {
  return vif.filter(
    (row) => typeof row.vif === "number" && row.vif >= VIF_LIMIT,
  );
}

export function AnalysisCoefficientTable({ view }: Props) {
  const showRatio = view.ratioLabel !== null;
  const level = formatLevel(view.interval?.level);
  const inflated = inflatedTerms(view.vif);

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)]">
      {view.model ? (
        <p className="border-b border-[var(--line)] px-3 py-2 text-[12px] font-medium text-ink">
          {view.model}
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[12px]">
          <caption className="sr-only">
            Coefficient estimates{view.outcome ? ` for ${view.outcome}` : ""}
          </caption>
          <thead>
            <tr className="border-b border-[var(--line)] text-[11px] uppercase tracking-wide text-ink-muted">
              <th scope="col" className="px-3 py-1.5 text-left font-medium">
                Term
              </th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">
                Estimate
              </th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">
                Std. error
              </th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">
                {view.statisticLabel}
              </th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">
                p
              </th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">
                {level} CI
              </th>
              {showRatio ? (
                <th scope="col" className="px-3 py-1.5 text-right font-medium">
                  {view.ratioLabel}
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--line)]">
            {view.coefficients.map((row) => (
              <CoefficientRow
                key={row.term}
                row={row}
                showRatio={showRatio}
                level={level}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="border-t border-[var(--line)]">
        <FitStatistics view={view} />
      </div>

      <div className="space-y-1 border-t border-[var(--line)] px-3 py-2 text-[11px] leading-relaxed text-ink-muted">
        <p>
          A marked row has p &lt; 0.05. The interval says more than the mark
          does: it is the range of coefficient values this data does not rule
          out.
        </p>
        {view.standardErrors ? (
          <p>Standard errors: {view.standardErrors}.</p>
        ) : null}
        {inflated.length > 0 ? (
          <p className="text-amber-800">
            High collinearity —{" "}
            {inflated
              .map((row) => `${row.term} (VIF ${formatStatistic(row.vif, 1)})`)
              .join(", ")}
            . These coefficients are not separately identified, however well the
            model as a whole fits.
          </p>
        ) : null}
      </div>
    </div>
  );
}
