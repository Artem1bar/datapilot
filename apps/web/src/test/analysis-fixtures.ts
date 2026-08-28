/**
 * Real statistics payloads, captured from the backend rather than invented.
 *
 * Every number below was produced by running the tier 4/5/6 operations in
 * `apps/api/app/services/` over a small frame and serializing the result the
 * way the API does. Hand-written fixtures would test the components against a
 * shape nobody ships; these test them against the one that arrives.
 */

import type {
  AnalysisOperationRecord,
  AnalysisStatistics,
  TableResult,
} from "@/types";

function record(
  index: number,
  op: string,
  label: string,
  n: number,
  statistics: AnalysisStatistics,
  extra: Partial<AnalysisOperationRecord> = {},
): AnalysisOperationRecord {
  return {
    index,
    op,
    label,
    params: {},
    n,
    n_excluded: 0,
    notes: [],
    statistics,
    ...extra,
  };
}

// ── Tier 4: ols with a categorical regressor ────────────────────────────────

export const OLS_STATISTICS: AnalysisStatistics = {
  model: "Ordinary least squares: salary on tenure, region",
  outcome: "salary",
  regressors: ["tenure", "region"],
  coefficients: [
    {
      term: "(Intercept)",
      coefficient: 30.116555,
      std_err: 0.450162,
      t: 66.901648,
      p_value: 1.65052e-94,
      ci_low: 29.224953,
      ci_high: 31.008157,
    },
    {
      term: "tenure",
      coefficient: 2.448504,
      std_err: 0.066687,
      t: 36.7161,
      p_value: 1.05275e-65,
      ci_low: 2.316421,
      ci_high: 2.580587,
    },
    {
      term: "region[North]",
      coefficient: 3.954125,
      std_err: 0.475372,
      t: 8.317964,
      p_value: 1.96582e-13,
      ci_low: 3.012591,
      ci_high: 4.895658,
    },
    {
      term: "region[West]",
      coefficient: -2.425844,
      std_err: 0.451845,
      t: -5.368749,
      p_value: 4.1256e-7,
      ci_low: -3.32078,
      ci_high: -1.530907,
    },
  ],
  reference_levels: { region: "East" },
  vif: [
    { term: "tenure", vif: 1.008779 },
    { term: "region[North]", vif: 1.346876 },
    { term: "region[West]", vif: 1.355813 },
  ],
  standard_errors: "HC3",
  statistic_column: "t",
  df_model: 3,
  df_resid: 116,
  r_squared: 0.937985,
  adj_r_squared: 0.936382,
  f_statistic: 610.013263,
  f_p_value: 7.79134e-71,
  rmse: 1.963956,
  aic: 510.535873,
  bic: 521.68584,
  confidence_interval: {
    low: 2.316421,
    high: 2.580587,
    level: 0.95,
    of: "the coefficient on tenure",
  },
  effect_size: { name: "R squared", value: 0.937985, magnitude: "large" },
  assumptions: [
    {
      name: "Multicollinearity (VIF)",
      passed: true,
      detail: "VIF tenure = 1.009; all below 10",
      statistic: 1.355813,
      p_value: null,
    },
    {
      name: "Homoskedasticity (Breusch-Pagan)",
      passed: false,
      detail:
        "Breusch-Pagan p = 0.0031; residual spread varies with the fitted values",
      statistic: 13.87,
      p_value: 0.0031,
    },
    {
      name: "Influential observations",
      passed: null,
      detail: "Cook's distance could not be computed for this fit",
      statistic: null,
      p_value: null,
    },
  ],
};

/** The same table the API sends beside the OLS payload. */
export const OLS_TABLE: TableResult = {
  columns: [
    "term",
    "coefficient",
    "std_err",
    "t",
    "p_value",
    "ci_low",
    "ci_high",
  ],
  rows: [
    [
      "(Intercept)",
      30.116555,
      0.450162,
      66.901648,
      1.65052e-94,
      29.224953,
      31.008157,
    ],
    ["tenure", 2.448504, 0.066687, 36.7161, 1.05275e-65, 2.316421, 2.580587],
    [
      "region[North]",
      3.954125,
      0.475372,
      8.317964,
      1.96582e-13,
      3.012591,
      4.895658,
    ],
    [
      "region[West]",
      -2.425844,
      0.451845,
      -5.368749,
      4.1256e-7,
      -3.32078,
      -1.530907,
    ],
  ],
  total_rows: 4,
};

// ── Tier 4: logit, which reports z and an odds ratio ─────────────────────────

export const LOGIT_STATISTICS: AnalysisStatistics = {
  model: "Logistic regression: P(responded == 'yes') on dose",
  outcome: "responded",
  regressors: ["dose"],
  coefficients: [
    {
      term: "(Intercept)",
      coefficient: -1.037384,
      std_err: 0.293389,
      z: -3.535863,
      p_value: 0.000406,
      ci_low: -1.612416,
      ci_high: -0.462352,
      odds_ratio: 0.354381,
      or_ci_low: 0.199405,
      or_ci_high: 0.629801,
    },
    {
      term: "dose",
      coefficient: 0.623444,
      std_err: 0.116262,
      z: 5.362416,
      p_value: 8.2116e-8,
      ci_low: 0.395575,
      ci_high: 0.851313,
      odds_ratio: 1.865341,
      or_ci_low: 1.485238,
      or_ci_high: 2.34272,
    },
  ],
  reference_levels: {},
  vif: [{ term: "dose", vif: 1.0 }],
  statistic_column: "z",
  standard_errors: "classical (observed information)",
  success_value: "yes",
  base_rate: 0.59,
  pseudo_r_squared: 0.13214,
  pseudo_r_squared_kind:
    "McFadden; not a share of variance, and small values are normal",
  llr_p_value: 1.2e-9,
  aic: 240.1,
  bic: 246.7,
  df_resid: 198,
  confidence_interval: {
    low: 1.485238,
    high: 2.34272,
    level: 0.95,
    of: "the odds ratio for dose",
  },
  assumptions: [
    {
      name: "Events per predictor",
      passed: true,
      detail:
        "82 observation(s) in the rarer outcome class across 1 estimated coefficient(s): 82 per predictor",
      statistic: 82,
      p_value: null,
    },
    {
      name: "Independence of observations",
      passed: null,
      detail:
        "a logit assumes one independent row per subject; repeated measures need a model that says so",
      statistic: null,
      p_value: null,
    },
  ],
};

/**
 * A count model. Its rate-ratio columns are `irr`, and this payload also
 * carries a null statistic — `f_statistic` is not defined for a GLM — which is
 * what a renderer must survive without printing "null".
 */
export const COUNT_STATISTICS: AnalysisStatistics = {
  model: "Poisson regression (log link): visits on ads",
  outcome: "visits",
  coefficients: [
    {
      term: "ads",
      coefficient: 0.349387,
      std_err: 0.043162,
      z: 8.094785,
      p_value: 5.73654e-16,
      ci_low: 0.264791,
      ci_high: 0.433983,
      irr: 1.418198,
      irr_ci_low: 1.303159,
      irr_ci_high: 1.543392,
    },
  ],
  reference_levels: {},
  vif: [],
  statistic_column: "z",
  family: "poisson",
  pseudo_r_squared: null,
  aic: null,
  df_resid: 148,
  assumptions: [],
};

// ── Tier 5: an ARIMA forecast, and the table it arrives with ─────────────────

export const ARIMA_STATISTICS: AnalysisStatistics = {
  model: "ARIMA(1, 0, 0) on value",
  coefficients: [
    {
      term: "const",
      coefficient: 49.956985,
      std_error: 0.215561,
      z: 231.753612,
      p_value: 5e-10,
      p_value_is_bound: true,
      ci95_low: 49.534494,
      ci95_high: 50.379476,
    },
  ],
  aic: 452.7,
  bic: 461.9,
  forecast: {
    periods: 3,
    level: 0.95,
    interval_meaning:
      "a prediction interval for a future observation, not a confidence interval for an average",
    rows: [
      {
        horizon: 1,
        date: "2028-05-31T00:00:00",
        forecast: 48.866315,
        std_error: 1.041025,
        ci95_low: 46.825943,
        ci95_high: 50.906687,
      },
      {
        horizon: 2,
        date: "2028-06-30T00:00:00",
        forecast: 49.284591,
        std_error: 1.222958,
        ci95_low: 46.887638,
        ci95_high: 51.681545,
      },
      {
        horizon: 3,
        date: "2028-07-31T00:00:00",
        forecast: 49.542457,
        std_error: 1.285369,
        ci95_low: 47.023181,
        ci95_high: 52.061733,
      },
    ],
  },
  effect_size: {
    name: "in-sample variance explained",
    value: 0.487,
    magnitude: "large",
  },
  assumptions: [
    {
      name: "No autocorrelation left in the model residuals",
      passed: true,
      detail: "Ljung-Box Q(9) = 6.42, p = 0.6975",
      statistic: 6.42,
      p_value: 0.6975,
    },
    {
      name: "Model correctness",
      passed: null,
      detail:
        "every number here is conditional on this order being the right one",
      statistic: null,
      p_value: null,
    },
  ],
};

/** Observed history then forecast, each row marked by `kind`. */
export const ARIMA_TABLE: TableResult = {
  columns: ["date", "value", "ci95_low", "ci95_high", "kind"],
  rows: [
    ["2028-03-31T00:00:00", 48.581374, null, null, "observed"],
    ["2028-04-30T00:00:00", 48.187841, null, null, "observed"],
    ["2028-05-31T00:00:00", 48.866315, 46.825943, 50.906687, "forecast"],
    ["2028-06-30T00:00:00", 49.284591, 46.887638, 51.681545, "forecast"],
    ["2028-07-31T00:00:00", 49.542457, 47.023181, 52.061733, "forecast"],
  ],
  total_rows: 5,
};

// ── Tier 6: survey estimation ───────────────────────────────────────────────

const SURVEY_DESIGN = {
  weights: "w",
  strata: null,
  cluster: null,
  sampling_fraction: null,
  variance_estimator:
    "Taylor linearization, ultimate-cluster (first-stage) approximation",
  n: 6,
  n_psu: 6,
  n_strata: 1,
  degrees_of_freedom: 5.0,
};

export const WEIGHTED_MEAN_STATISTICS: AnalysisStatistics = {
  estimate: "Weighted mean of score, using w as the design weight",
  n: 6,
  design: SURVEY_DESIGN,
  degrees_of_freedom: 5.0,
  weighted_mean: 42.5,
  unweighted_mean: 35.0,
  standard_error: 6.479133,
  confidence_interval: {
    low: 25.844858,
    high: 59.155142,
    level: 0.95,
    of: "the population mean of score",
  },
  relative_standard_error: 0.15245,
  sum_of_weights: 12.0,
  effect_size: {
    name: "Weighting shift (Cohen's d)",
    value: 0.400892,
    magnitude: "small",
  },
  assumptions: [
    {
      name: "Weights are design weights",
      passed: null,
      detail:
        "nothing in the data says whether w is a design weight or an arbitrary column",
      statistic: null,
      p_value: null,
    },
  ],
};

export const DESIGN_EFFECT_STATISTICS: AnalysisStatistics = {
  estimate: "Design effect and effective sample size for score",
  n: 6,
  reading:
    "6 responses carry the statistical weight of about 4.8 equally-weighted ones. Precision follows the effective sample size, not the response count.",
  design_effect_kish: 1.25,
  design_effect_design_based: 0.891593,
  effective_sample_size: 4.8,
  weight_cv: 0.5,
  sum_of_weights: 12.0,
  weighted_mean: 42.5,
  unweighted_mean: 35.0,
  design: SURVEY_DESIGN,
  degrees_of_freedom: 5.0,
  assumptions: [],
};

export const WEIGHTED_CROSSTAB_STATISTICS: AnalysisStatistics = {
  test: "Rao-Scott corrected chi-square test of independence (arm x outcome)",
  statistic: 14.052392,
  dof: 1,
  p_value: 0.000178,
  correction_factor: 1.176203,
  uncorrected_statistic: 16.528466,
  naive_weighted_statistic: 28.942607,
  naive_weighted_p_value: 7.45548e-8,
  effective_sample_size: 170.038677,
  n_unweighted: 200,
  estimated_population: 350.215283,
  design: { ...SURVEY_DESIGN, n: 200, n_psu: 200, degrees_of_freedom: 199.0 },
  degrees_of_freedom: 199.0,
  assumptions: [],
};

/** A grouped weighted mean: every estimate lives in the table, none in `stats`. */
export const GROUPED_WEIGHTED_STATISTICS: AnalysisStatistics = {
  estimate: "Weighted mean of score, using w as the design weight",
  n: 6,
  design: SURVEY_DESIGN,
  degrees_of_freedom: 5.0,
  assumptions: [],
};

// ── Operation records, as provenance carries them ───────────────────────────

export const OLS_OPERATION = record(
  0,
  "ols",
  "Salary on tenure and region",
  120,
  OLS_STATISTICS,
  {
    n_excluded: 8,
    notes: ["Categorical baselines: region = 'East'."],
  },
);

export const LOGIT_OPERATION = record(
  0,
  "logit",
  "Response on dose",
  200,
  LOGIT_STATISTICS,
);

export const ARIMA_OPERATION = record(
  0,
  "arima",
  "Monthly value forecast",
  160,
  ARIMA_STATISTICS,
);

export const WEIGHTED_MEAN_OPERATION = record(
  0,
  "weighted_mean",
  "Weighted mean score",
  6,
  WEIGHTED_MEAN_STATISTICS,
);

export const DESIGN_EFFECT_OPERATION = record(
  0,
  "design_effect",
  "Design effect for score",
  6,
  DESIGN_EFFECT_STATISTICS,
);

/** A tier-1 operation: nothing the results card can render better than a table. */
export const DESCRIPTIVE_OPERATION = record(
  0,
  "value_counts",
  "Rows by region",
  480,
  {
    assumptions: [],
  },
);

/** The scripts the API attaches to provenance under `code`. */
export const RAW_CODE = {
  python: "import pandas as pd\n\ndf = pd.read_csv('data.csv')\n",
  r: "library(dplyr)\n\ndf <- read.csv('data.csv')\n",
  r_incomplete: ["quantile_regression"],
};
