import {
  formatCount,
  formatInterval,
  formatLevel,
  formatStatistic,
} from "@/lib/analysis-format";
import type { AnalysisSurveyDesign, AnalysisWeightedView } from "@/types";

/**
 * A survey estimate, beside the unweighted number it corrects.
 *
 * Two things a general-purpose data tool gets wrong about survey data, both
 * shown here rather than explained in prose.
 *
 * The unweighted mean is not the estimate. It is the mean of whoever answered,
 * and on a weighted survey it answers a question nobody asked. Putting the two
 * side by side makes the size of that correction a visible property of the
 * answer instead of a footnote.
 *
 * And the response count is not the sample size. Weighting buys representativeness
 * with precision: 2,000 responses under a design effect of 1.6 carry the
 * statistical weight of about 1,240 equally-weighted ones, and every interval on
 * the page follows the second number, not the first.
 */

interface Props {
  view: AnalysisWeightedView;
}

function Figure({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="px-3 py-2">
      <p className="text-[11px] text-ink-muted">{label}</p>
      <p
        className={`tabular-nums ${emphasis ? "text-[16px] font-semibold text-ink" : "text-[14px] text-ink"}`}
      >
        {value}
      </p>
    </div>
  );
}

function DesignSummary({ design }: { design: AnalysisSurveyDesign }) {
  const entries = [
    design.weights ? `weights ${design.weights}` : null,
    design.strata ? `stratified by ${design.strata}` : "unstratified",
    design.cluster ? `clustered by ${design.cluster}` : "unclustered",
    typeof design.degrees_of_freedom === "number"
      ? `${design.degrees_of_freedom} df`
      : null,
  ].filter(Boolean);

  return (
    <p className="border-t border-[var(--line)] px-3 py-2 text-[11px] leading-relaxed text-ink-muted">
      Design: {entries.join(" · ")}.
      {design.variance_estimator
        ? ` Variance by ${design.variance_estimator}.`
        : ""}
    </p>
  );
}

/** The Rao-Scott contrast: what the corrected test says against the naive one. */
function RaoScott({
  raoScott,
}: {
  raoScott: NonNullable<AnalysisWeightedView["raoScott"]>;
}) {
  return (
    <div className="border-t border-[var(--line)] px-3 py-2 text-[11px] leading-relaxed text-ink-muted">
      <p>
        <span className="font-medium text-ink">
          Rao-Scott χ² = {formatStatistic(raoScott.statistic)}
        </span>
        {raoScott.dof !== null
          ? ` on ${formatStatistic(raoScott.dof, 0)} df`
          : ""}
        , p = {formatStatistic(raoScott.pValue)}, after dividing by a design
        correction of {formatStatistic(raoScott.correctionFactor)}.
      </p>
      <p className="mt-1">
        Run naively on the weighted counts the same table gives χ² ={" "}
        {formatStatistic(raoScott.naive)} — it treats every weighted unit as an
        independent observation, which is the commonest error in published
        survey analysis.
      </p>
    </div>
  );
}

/** The sentence this whole component exists to make readable. */
function EffectiveSampleSize({ view }: Props) {
  const deff = view.designEffectDesignBased ?? view.designEffectKish;
  if (view.effectiveSampleSize === null && deff === null) return null;

  return (
    <div className="border-t border-[var(--line)] bg-sky-50/40 px-3 py-2">
      <div className="grid grid-cols-3 gap-2">
        <Figure label="Respondents" value={formatCount(view.respondents)} />
        <Figure
          label="Effective sample size"
          value={formatCount(view.effectiveSampleSize)}
          emphasis
        />
        <Figure label="Design effect" value={formatStatistic(deff, 2)} />
      </div>
      <p className="px-3 pb-1 text-[11px] leading-relaxed text-ink-muted">
        {view.reading ??
          "Precision follows the effective sample size, not the response count."}
      </p>
    </div>
  );
}

export function AnalysisWeightedEstimate({ view }: Props) {
  const hasPair = view.weighted !== null || view.unweighted !== null;
  const difference =
    view.weighted !== null && view.unweighted !== null
      ? view.weighted - view.unweighted
      : null;

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)]">
      {view.estimate ? (
        <p className="border-b border-[var(--line)] px-3 py-2 text-[12px] font-medium text-ink">
          {view.estimate}
        </p>
      ) : null}

      {hasPair ? (
        <div className="grid grid-cols-2 divide-x divide-[var(--line)]">
          <Figure
            label={view.weightedLabel}
            value={formatStatistic(view.weighted)}
            emphasis
          />
          <Figure
            label={view.unweightedLabel}
            value={formatStatistic(view.unweighted)}
          />
        </div>
      ) : null}

      {difference !== null ? (
        <p className="px-3 pb-2 text-[11px] leading-relaxed text-ink-muted">
          Weighting moved the estimate by {formatStatistic(difference)}. The
          unweighted figure describes the respondents; only the weighted one
          estimates the population.
        </p>
      ) : null}

      {view.standardError !== null || view.interval ? (
        <div className="grid grid-cols-2 divide-x divide-[var(--line)] border-t border-[var(--line)]">
          <Figure
            label="Standard error"
            value={formatStatistic(view.standardError)}
          />
          <Figure
            label={`${formatLevel(view.interval?.level)} CI`}
            value={formatInterval(
              view.interval?.low ?? null,
              view.interval?.high ?? null,
            )}
          />
        </div>
      ) : null}

      <EffectiveSampleSize view={view} />

      {view.estimatedPopulation !== null ? (
        <p className="border-t border-[var(--line)] px-3 py-2 text-[11px] leading-relaxed text-ink-muted">
          The weights sum to {formatCount(view.estimatedPopulation)}, which is
          the population size this estimate claims.
        </p>
      ) : null}

      {view.raoScott ? <RaoScott raoScott={view.raoScott} /> : null}
      {view.design ? <DesignSummary design={view.design} /> : null}
    </div>
  );
}
