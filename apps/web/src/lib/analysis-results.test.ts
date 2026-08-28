import { describe, it, expect } from "vitest";
import {
  toForecastView,
  toRegressionView,
  toResultsCard,
  toWeightedView,
  withReferenceRows,
} from "./analysis-results";
import {
  ARIMA_OPERATION,
  ARIMA_STATISTICS,
  ARIMA_TABLE,
  COUNT_STATISTICS,
  DESCRIPTIVE_OPERATION,
  DESIGN_EFFECT_STATISTICS,
  GROUPED_WEIGHTED_STATISTICS,
  LOGIT_STATISTICS,
  OLS_OPERATION,
  OLS_STATISTICS,
  OLS_TABLE,
  WEIGHTED_CROSSTAB_STATISTICS,
  WEIGHTED_MEAN_STATISTICS,
} from "@/test/analysis-fixtures";
import type { AnalysisCoefficientRow, AnalysisStatistics } from "@/types";

describe("toRegressionView", () => {
  it("returns null for an operation that fitted no model", () => {
    expect(toRegressionView({})).toBeNull();
    expect(toRegressionView({ coefficients: [] })).toBeNull();
  });

  it("reads the regression dialect: std_err, ci_low, ci_high, t", () => {
    const view = toRegressionView(OLS_STATISTICS);
    const tenure = view?.coefficients.find((row) => row.term === "tenure");

    expect(view?.statisticLabel).toBe("t");
    expect(tenure?.estimate).toBe(2.448504);
    expect(tenure?.stdError).toBe(0.066687);
    expect(tenure?.statistic).toBe(36.7161);
    expect(tenure?.ciLow).toBe(2.316421);
    expect(tenure?.ciHigh).toBe(2.580587);
  });

  it("reads the time-series dialect: std_error, ci95_low, ci95_high, z", () => {
    const view = toRegressionView(ARIMA_STATISTICS);
    const term = view?.coefficients[0];

    // The ARIMA payload names none of these the way the regression tier does,
    // and carries no statistic_column at all.
    expect(view?.statisticLabel).toBe("z");
    expect(term?.stdError).toBe(0.215561);
    expect(term?.ciLow).toBe(49.534494);
    expect(term?.ciHigh).toBe(50.379476);
    expect(term?.pValueIsBound).toBe(true);
  });

  it("carries the odds ratio and its interval for a logit", () => {
    const view = toRegressionView(LOGIT_STATISTICS);
    const dose = view?.coefficients.find((row) => row.term === "dose");

    expect(view?.ratioLabel).toBe("Odds ratio");
    expect(dose?.ratio).toEqual({
      value: 1.865341,
      low: 1.485238,
      high: 2.34272,
    });
  });

  it("carries the incidence rate ratio for a count model", () => {
    const view = toRegressionView(COUNT_STATISTICS);
    expect(view?.ratioLabel).toBe("Rate ratio (IRR)");
    expect(view?.coefficients[0].ratio?.value).toBe(1.418198);
  });

  it("splits a categorical indicator into its variable and level", () => {
    const view = toRegressionView(OLS_STATISTICS);
    const north = view?.coefficients.find(
      (row) => row.term === "region[North]",
    );
    const tenure = view?.coefficients.find((row) => row.term === "tenure");

    expect(north).toMatchObject({ variable: "region", level: "North" });
    expect(tenure).toMatchObject({ variable: null, level: null });
  });

  it("keeps a fit statistic the backend could not compute, as null", () => {
    // The key is present and its value is null: the model reported that it
    // could not compute it, which is not the same as never having tried.
    const fit = toRegressionView(COUNT_STATISTICS)?.fit ?? [];
    expect(fit.find((stat) => stat.label === "Pseudo R²")).toEqual({
      label: "Pseudo R²",
      value: null,
      kind: undefined,
    });
    expect(fit.find((stat) => stat.label === "R²")).toBeUndefined();
  });

  it("survives a payload with no optional statistics at all", () => {
    const bare: AnalysisStatistics = {
      coefficients: [{ term: "x", coefficient: null, p_value: null }],
    };
    const view = toRegressionView(bare);

    expect(view?.fit).toEqual([]);
    expect(view?.vif).toEqual([]);
    expect(view?.standardErrors).toBeNull();
    expect(view?.coefficients[0]).toMatchObject({
      estimate: null,
      stdError: null,
      ciLow: null,
    });
  });
});

describe("withReferenceRows", () => {
  const rows: AnalysisCoefficientRow[] = [
    { variable: null, level: null, term: "tenure" },
    { variable: "region", level: "North", term: "region[North]" },
    { variable: "region", level: "West", term: "region[West]" },
  ].map((partial) => ({
    ...partial,
    isReference: false,
    estimate: 1,
    stdError: 1,
    statistic: 1,
    pValue: 0.5,
    pValueIsBound: false,
    ciLow: 0,
    ciHigh: 2,
    ratio: null,
  })) as AnalysisCoefficientRow[];

  it("puts the baseline immediately above the indicators it anchors", () => {
    const placed = withReferenceRows(rows, { region: "East" });
    expect(placed.map((row) => [row.term, row.isReference])).toEqual([
      ["tenure", false],
      ["region[East]", true],
      ["region[North]", false],
      ["region[West]", false],
    ]);
  });

  it("keeps a baseline whose indicators are absent rather than dropping it", () => {
    // The estimates are still relative to it, so silently omitting it would
    // leave the table uninterpretable.
    const placed = withReferenceRows(rows, { region: "East", arm: "control" });
    expect(
      placed.some((row) => row.term === "arm[control]" && row.isReference),
    ).toBe(true);
  });

  it("adds nothing when the model has no categorical regressor", () => {
    expect(withReferenceRows(rows, {})).toHaveLength(rows.length);
  });
});

describe("toForecastView", () => {
  it("returns null for an operation that produced no forecast", () => {
    expect(toForecastView({})).toBeNull();
    expect(toForecastView({ forecast: null })).toBeNull();
  });

  it("separates observed from forecast and keeps every interval", () => {
    const view = toForecastView(ARIMA_STATISTICS, ARIMA_TABLE);
    const forecasts =
      view?.points.filter((point) => point.observed === null) ?? [];

    expect(view?.hasInterval).toBe(true);
    expect(forecasts).toHaveLength(3);
    expect(forecasts.every((point) => point.interval !== null)).toBe(true);
    expect(forecasts[0].interval).toEqual([46.825943, 50.906687]);
  });

  it("anchors the forecast on the last observed value rather than inventing one", () => {
    const view = toForecastView(ARIMA_STATISTICS, ARIMA_TABLE);
    const seam = view?.points[1];

    // 48.187841 is the last observed value, replayed so the two lines meet.
    // The band is degenerate there because that value is known, not estimated.
    expect(seam?.observed).toBe(48.187841);
    expect(seam?.forecast).toBe(48.187841);
    expect(seam?.interval).toEqual([48.187841, 48.187841]);
  });

  it("falls back to the forecast rows when no table came with the payload", () => {
    const view = toForecastView(ARIMA_STATISTICS);
    expect(view?.points).toHaveLength(3);
    expect(view?.points.every((point) => point.observed === null)).toBe(true);
    expect(view?.hasInterval).toBe(true);
  });

  it("reports a forecast whose bounds are missing as having no interval", () => {
    // A point forecast with its uncertainty deleted must be renderable as the
    // problem it is, not drawn as a line.
    const view = toForecastView({
      forecast: {
        periods: 1,
        level: 0.95,
        rows: [
          {
            horizon: 1,
            date: "2028-05-31T00:00:00",
            forecast: 48.9,
            ci95_low: null,
            ci95_high: null,
          },
        ],
      },
    });
    expect(view?.points[0].interval).toBeNull();
    expect(view?.hasInterval).toBe(false);
  });

  it("ignores a table that is not a forecast table", () => {
    const view = toForecastView(ARIMA_STATISTICS, OLS_TABLE);
    // No date/value/kind columns, so it falls back to the statistics rows.
    expect(view?.points).toHaveLength(3);
  });
});

describe("toWeightedView", () => {
  it("returns null when no sampling design was involved", () => {
    expect(toWeightedView(OLS_STATISTICS)).toBeNull();
  });

  it("pairs the weighted mean with the unweighted one", () => {
    const view = toWeightedView(WEIGHTED_MEAN_STATISTICS);
    expect(view).toMatchObject({
      weightedLabel: "Weighted mean",
      weighted: 42.5,
      unweightedLabel: "Unweighted mean",
      unweighted: 35.0,
      standardError: 6.479133,
      respondents: 6,
    });
  });

  it("switches to the total's labels when the operation estimated a total", () => {
    const view = toWeightedView({
      design: WEIGHTED_MEAN_STATISTICS.design,
      weighted_total: 510,
      unweighted_sum: 210,
    });
    expect(view).toMatchObject({
      weightedLabel: "Weighted total",
      weighted: 510,
      unweightedLabel: "Unweighted sum",
      unweighted: 210,
    });
  });

  it("carries the design effect and the effective sample size", () => {
    const view = toWeightedView(DESIGN_EFFECT_STATISTICS);
    expect(view?.effectiveSampleSize).toBe(4.8);
    expect(view?.designEffectKish).toBe(1.25);
    expect(view?.reading).toContain("4.8 equally-weighted ones");
  });

  it("carries the Rao-Scott contrast on a weighted crosstab", () => {
    const view = toWeightedView(WEIGHTED_CROSSTAB_STATISTICS);
    expect(view?.raoScott).toMatchObject({
      statistic: 14.052392,
      naive: 28.942607,
      correctionFactor: 1.176203,
    });
    expect(view?.respondents).toBe(200);
  });

  it("reports no pair for a grouped estimate rather than a fabricated one", () => {
    // Every estimate lives in the result table; inventing a headline pair from
    // the whole sample would answer a question nobody asked.
    const view = toWeightedView(GROUPED_WEIGHTED_STATISTICS);
    expect(view?.weighted).toBeNull();
    expect(view?.unweighted).toBeNull();
    expect(view?.raoScott).toBeNull();
    expect(view?.design?.weights).toBe("w");
  });
});

describe("toResultsCard", () => {
  it("returns null when nothing was computed", () => {
    expect(toResultsCard(undefined, undefined)).toBeNull();
    expect(toResultsCard([], [])).toBeNull();
  });

  it("returns null when no operation has a payload worth rendering", () => {
    expect(toResultsCard([DESCRIPTIVE_OPERATION], [])).toBeNull();
  });

  it("keeps only the operations with a rich payload", () => {
    const card = toResultsCard(
      [OLS_OPERATION, { ...DESCRIPTIVE_OPERATION, index: 1 }],
      [OLS_TABLE, { columns: [], rows: [], total_rows: 0 }],
    );
    expect(card?.blocks.map((block) => block.op)).toEqual(["ols"]);
    expect(card?.blocks[0]).toMatchObject({ n: 120, nExcluded: 8 });
  });

  it("pairs an operation with the table at its own index", () => {
    const card = toResultsCard(
      [
        { ...DESCRIPTIVE_OPERATION, index: 0 },
        { ...ARIMA_OPERATION, index: 1 },
      ],
      [OLS_TABLE, ARIMA_TABLE],
    );
    // Index 1 is the ARIMA table, so the observed history is there to draw.
    expect(card?.blocks[0].forecast?.points).toHaveLength(5);
  });

  it("carries every assumption check through to the block", () => {
    const card = toResultsCard([OLS_OPERATION], [OLS_TABLE]);
    expect(card?.blocks[0].assumptions.map((check) => check.passed)).toEqual([
      true,
      false,
      null,
    ]);
  });
});
