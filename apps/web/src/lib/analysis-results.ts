/**
 * Turn the API's statistics payloads into the shapes the result components render.
 *
 * The payloads are a faithful transcript of what statsmodels produced, which is
 * the right thing for a provenance record and the wrong thing for a component:
 * a standard error arrives as `std_err` from the regression tier and as
 * `std_error` from the time-series tier, and a confidence bound has three
 * spellings between them. Reconciling that here means no component has to know
 * which model produced its row, and means the reconciliation is testable
 * without rendering anything.
 *
 * Nothing in this module invents a value. A statistic the backend reported as
 * null stays null all the way to the screen, where it renders as an em dash.
 */

import type {
  AnalysisAssumption,
  AnalysisCoefficientRow,
  AnalysisFitStatistic,
  AnalysisForecastPoint,
  AnalysisForecastView,
  AnalysisOperationRecord,
  AnalysisRawCoefficient,
  AnalysisRegressionView,
  AnalysisResultBlock,
  AnalysisResultsPayload,
  AnalysisStatistics,
  AnalysisWeightedView,
  TableResult,
} from "@/types";

/** A categorical design term, e.g. `region[West]`. */
const INDICATOR_TERM = /^(.+)\[(.*)\]$/;

/** Model-level statistics, in the order a reader scans them. Only the keys a
 *  given model actually reported are rendered — presence is the filter, not the
 *  operation name, so a new model's fit block needs no change here. */
const FIT_FIELDS: ReadonlyArray<{
  readonly key: keyof AnalysisStatistics;
  readonly label: string;
  readonly kind?: AnalysisFitStatistic["kind"];
}> = [
  { key: "r_squared", label: "R²" },
  { key: "adj_r_squared", label: "Adjusted R²" },
  { key: "pseudo_r_squared", label: "Pseudo R²" },
  { key: "f_statistic", label: "F" },
  { key: "f_p_value", label: "F p-value", kind: "p_value" },
  { key: "llr_p_value", label: "LR test p-value", kind: "p_value" },
  { key: "rmse", label: "RMSE" },
  { key: "base_rate", label: "Base rate" },
  { key: "tau", label: "Quantile (tau)" },
  { key: "aic", label: "AIC" },
  { key: "bic", label: "BIC" },
  { key: "df_resid", label: "Residual df", kind: "integer" },
];

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Split `region[West]` into its variable and level; numeric terms have neither. */
function splitTerm(term: string): {
  variable: string | null;
  level: string | null;
} {
  const match = INDICATOR_TERM.exec(term);
  return match
    ? { variable: match[1], level: match[2] }
    : { variable: null, level: null };
}

function ratioOf(raw: AnalysisRawCoefficient) {
  if (raw.odds_ratio !== undefined) {
    return {
      value: numberOrNull(raw.odds_ratio),
      low: numberOrNull(raw.or_ci_low),
      high: numberOrNull(raw.or_ci_high),
    };
  }
  if (raw.irr !== undefined) {
    return {
      value: numberOrNull(raw.irr),
      low: numberOrNull(raw.irr_ci_low),
      high: numberOrNull(raw.irr_ci_high),
    };
  }
  return null;
}

/** One coefficient row, with both API dialects reconciled. */
function toCoefficientRow(raw: AnalysisRawCoefficient): AnalysisCoefficientRow {
  const { variable, level } = splitTerm(raw.term);
  return {
    term: raw.term,
    variable,
    level,
    isReference: false,
    estimate: numberOrNull(raw.coefficient),
    stdError: numberOrNull(raw.std_err ?? raw.std_error),
    statistic: numberOrNull(raw.t ?? raw.z),
    pValue: numberOrNull(raw.p_value),
    pValueIsBound: raw.p_value_is_bound === true,
    ciLow: numberOrNull(raw.ci_low ?? raw.ci95_low),
    ciHigh: numberOrNull(raw.ci_high ?? raw.ci95_high),
    ratio: ratioOf(raw),
  };
}

function referenceRow(variable: string, level: string): AnalysisCoefficientRow {
  return {
    term: `${variable}[${level}]`,
    variable,
    level,
    isReference: true,
    estimate: null,
    stdError: null,
    statistic: null,
    pValue: null,
    pValueIsBound: false,
    ciLow: null,
    ciHigh: null,
    ratio: null,
  };
}

/**
 * Place each categorical's omitted baseline immediately above its indicators.
 *
 * A baseline listed in a footnote is a baseline most readers will not read, and
 * every indicator coefficient below it is meaningless without it. A baseline
 * whose variable has no indicators in the table is appended rather than
 * dropped, because it is still what the estimates are relative to.
 */
export function withReferenceRows(
  rows: readonly AnalysisCoefficientRow[],
  referenceLevels: Readonly<Record<string, string>>,
): AnalysisCoefficientRow[] {
  const pending = new Map(Object.entries(referenceLevels));
  const placed: AnalysisCoefficientRow[] = [];

  for (const row of rows) {
    const level = row.variable !== null ? pending.get(row.variable) : undefined;
    if (row.variable !== null && level !== undefined) {
      placed.push(referenceRow(row.variable, level));
      pending.delete(row.variable);
    }
    placed.push(row);
  }
  for (const [variable, level] of [...pending].sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    placed.push(referenceRow(variable, level));
  }
  return placed;
}

function fitStatistics(stats: AnalysisStatistics): AnalysisFitStatistic[] {
  return FIT_FIELDS.filter((field) => stats[field.key] !== undefined).map(
    (field) => ({
      label: field.label,
      value: numberOrNull(stats[field.key]),
      kind: field.kind,
    }),
  );
}

function ratioLabelOf(
  coefficients: readonly AnalysisRawCoefficient[],
): string | null {
  if (coefficients.some((row) => row.odds_ratio !== undefined))
    return "Odds ratio";
  if (coefficients.some((row) => row.irr !== undefined))
    return "Rate ratio (IRR)";
  return null;
}

/** The regression view, or null when this operation fitted no model. */
export function toRegressionView(
  stats: AnalysisStatistics,
): AnalysisRegressionView | null {
  const raw = stats.coefficients;
  if (!raw?.length) return null;

  const referenceLevels = stats.reference_levels ?? {};
  return {
    model: stats.model ?? null,
    outcome: stats.outcome ?? null,
    statisticLabel:
      stats.statistic_column ??
      (raw.some((row) => row.z !== undefined) ? "z" : "t"),
    ratioLabel: ratioLabelOf(raw),
    coefficients: withReferenceRows(raw.map(toCoefficientRow), referenceLevels),
    referenceLevels: Object.entries(referenceLevels)
      .map(([variable, level]) => ({ variable, level }))
      .sort((a, b) => a.variable.localeCompare(b.variable)),
    fit: fitStatistics(stats),
    standardErrors: stats.standard_errors ?? null,
    vif: stats.vif ?? [],
    interval: stats.confidence_interval ?? null,
  };
}

// ── Forecasts ───────────────────────────────────────────────────────────────

/** Read one column out of the operation's result table, by name. */
function column(
  table: TableResult | undefined,
  name: string,
): unknown[] | null {
  const index = table?.columns.indexOf(name) ?? -1;
  return table && index >= 0 ? table.rows.map((row) => row[index]) : null;
}

function pointsFromTable(table: TableResult): AnalysisForecastPoint[] | null {
  const dates = column(table, "date");
  const values = column(table, "value");
  const kinds = column(table, "kind");
  const low = column(table, "ci95_low");
  const high = column(table, "ci95_high");
  if (!dates || !values || !kinds) return null;

  return dates.map((date, i) => {
    const isForecast = kinds[i] === "forecast";
    const value = numberOrNull(values[i]);
    const bounds = [numberOrNull(low?.[i]), numberOrNull(high?.[i])] as const;
    return {
      date: String(date),
      observed: isForecast ? null : value,
      forecast: isForecast ? value : null,
      interval:
        bounds[0] !== null && bounds[1] !== null
          ? [bounds[0], bounds[1]]
          : null,
    };
  });
}

/**
 * Join the forecast to the history it continues.
 *
 * The last observed value is repeated into the forecast series so the two lines
 * meet rather than leaving a one-period gap, and the band is anchored there at
 * zero width. Both are the observed value plotted again, not a new number: at
 * the last observation the series is known, so the interval around it really is
 * degenerate.
 */
function anchorForecast(
  points: AnalysisForecastPoint[],
): AnalysisForecastPoint[] {
  const seam = points.findIndex((point) => point.forecast !== null);
  if (seam < 1) return points;

  const anchor = points[seam - 1].observed;
  if (anchor === null) return points;
  return points.map((point, i) =>
    i === seam - 1
      ? {
          ...point,
          forecast: anchor,
          interval: [anchor, anchor] as [number, number],
        }
      : point,
  );
}

/** Forecast steps alone, for a payload that arrived without its result table. */
function pointsFromStats(
  rows: readonly {
    date: string;
    forecast: number | null;
    ci95_low: number | null;
    ci95_high: number | null;
  }[],
): AnalysisForecastPoint[] {
  return rows.map((row) => ({
    date: row.date,
    observed: null,
    forecast: numberOrNull(row.forecast),
    interval:
      numberOrNull(row.ci95_low) !== null &&
      numberOrNull(row.ci95_high) !== null
        ? ([row.ci95_low, row.ci95_high] as [number, number])
        : null,
  }));
}

/** The forecast view, or null when this operation produced no forecast. */
export function toForecastView(
  stats: AnalysisStatistics,
  table?: TableResult,
): AnalysisForecastView | null {
  const forecast = stats.forecast;
  if (!forecast) return null;

  const fromTable = table ? pointsFromTable(table) : null;
  const points = fromTable
    ? anchorForecast(fromTable)
    : pointsFromStats(forecast.rows);
  if (!points.length) return null;

  return {
    model: stats.model ?? null,
    level: forecast.level ?? 0.95,
    periods: forecast.periods,
    intervalMeaning: forecast.interval_meaning ?? null,
    points,
    // A forecast drawn without its interval is the most misleading thing this
    // product could render, so whether one exists is part of the view rather
    // than something the chart discovers while drawing.
    hasInterval: points.some(
      (point) => point.forecast !== null && point.interval !== null,
    ),
  };
}

// ── Survey estimates ────────────────────────────────────────────────────────

/** The weighted/unweighted pair this operation reported, if it reported one. */
function weightedPair(stats: AnalysisStatistics) {
  if (stats.weighted_total !== undefined) {
    return {
      weightedLabel: "Weighted total",
      weighted: numberOrNull(stats.weighted_total),
      unweightedLabel: "Unweighted sum",
      unweighted: numberOrNull(stats.unweighted_sum),
    };
  }
  return {
    weightedLabel: "Weighted mean",
    weighted: numberOrNull(stats.weighted_mean),
    unweightedLabel: "Unweighted mean",
    unweighted: numberOrNull(stats.unweighted_mean),
  };
}

function raoScottOf(
  stats: AnalysisStatistics,
): AnalysisWeightedView["raoScott"] {
  if (stats.correction_factor === undefined) return null;
  return {
    statistic: numberOrNull(stats.statistic),
    uncorrected: numberOrNull(stats.uncorrected_statistic),
    naive: numberOrNull(stats.naive_weighted_statistic),
    correctionFactor: numberOrNull(stats.correction_factor),
    dof: numberOrNull(stats.dof),
    pValue: numberOrNull(stats.p_value),
    naivePValue: numberOrNull(stats.naive_weighted_p_value),
  };
}

/**
 * The survey view, or null when no sampling design was involved.
 *
 * Every tier-6 payload carries a `design` block, so its presence is what
 * decides — not the operation name, which would have to be enumerated.
 */
export function toWeightedView(
  stats: AnalysisStatistics,
): AnalysisWeightedView | null {
  if (!stats.design) return null;
  const pair = weightedPair(stats);

  return {
    estimate: stats.estimate ?? null,
    ...pair,
    standardError: numberOrNull(stats.standard_error),
    relativeStandardError: numberOrNull(stats.relative_standard_error),
    interval: stats.confidence_interval ?? null,
    respondents: numberOrNull(stats.n ?? stats.n_unweighted),
    effectiveSampleSize: numberOrNull(stats.effective_sample_size),
    designEffectKish: numberOrNull(stats.design_effect_kish),
    designEffectDesignBased: numberOrNull(stats.design_effect_design_based),
    sumOfWeights: numberOrNull(stats.sum_of_weights),
    estimatedPopulation: numberOrNull(stats.estimated_population),
    reading: stats.reading ?? null,
    design: stats.design,
    raoScott: raoScottOf(stats),
  };
}

// ── Assembly ────────────────────────────────────────────────────────────────

function toBlock(
  operation: AnalysisOperationRecord,
  table: TableResult | undefined,
): AnalysisResultBlock | null {
  const stats = operation.statistics ?? {};
  const regression = toRegressionView(stats);
  const forecast = toForecastView(stats, table);
  const weighted = toWeightedView(stats);
  if (!regression && !forecast && !weighted) return null;

  return {
    index: operation.index,
    op: operation.op,
    label: operation.label,
    n: operation.n,
    nExcluded: operation.n_excluded,
    notes: operation.notes ?? [],
    assumptions: (stats.assumptions ?? []) as readonly AnalysisAssumption[],
    regression,
    forecast,
    weighted,
  };
}

/**
 * Build the results card for one answer, or null when there is nothing to show.
 *
 * Only operations with a payload the card can render better than a generic grid
 * get a block: a regression, a forecast, or a survey estimate. Descriptive
 * operations are already legible as tables, and duplicating them here would
 * bury the results that are not.
 *
 * `tables` is index-aligned with `operations` — the API builds both from the
 * same list of results, in order — which is how a forecast finds the observed
 * history that its own statistics payload does not carry.
 */
export function toResultsCard(
  operations: readonly AnalysisOperationRecord[] | undefined,
  tables: readonly TableResult[] | undefined,
): AnalysisResultsPayload | null {
  if (!operations?.length) return null;

  const blocks = operations
    .map((operation) => toBlock(operation, tables?.[operation.index]))
    .filter((block): block is AnalysisResultBlock => block !== null);

  return blocks.length ? { type: "analysis_results", blocks } : null;
}
