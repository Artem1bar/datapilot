// ── Chat V2 Types ──────────────────────────────────────────────────────────

import type { ChartConfig, TableResult, CleaningStep } from "./index";

/** Message roles extended with system status messages. */
export type MessageRole = "user" | "assistant" | "system";

/** Workflow step identifiers for the cleaning pipeline. */
export type WorkflowStepId = "inspect" | "plan" | "clean" | "validate";

export type WorkflowStepStatus = "pending" | "active" | "complete" | "error";

export interface WorkflowStep {
  readonly id: WorkflowStepId;
  readonly label: string;
  readonly status: WorkflowStepStatus;
}

export interface WorkflowState {
  readonly steps: readonly WorkflowStep[];
  readonly datasetId: string;
  readonly datasetFilename: string;
}

/**
 * A dispatched clean job the UI is (or should be) watching. Persisted so a
 * refresh mid-job can re-attach: poll the job and restore the progress card.
 * Everything here must be serializable.
 */
export interface ActiveCleaningJob {
  readonly jobId: string;
  readonly datasetId: string;
  readonly datasetFilename: string;
  /** Id of the persisted progress-card message this job drives. */
  readonly progressMessageId: string;
  readonly rowsBefore: number;
  /** The approved steps, kept so a failure after refresh can offer retry. */
  readonly steps: readonly CleaningStep[];
  readonly startedAt: string;
}

/** Session metadata persisted across page loads. */
export interface Session {
  readonly id: string;
  readonly title: string;
  readonly subtitle: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly pinned: boolean;
  readonly datasetId: string | null;
}

// ── Card Payloads ───────────────────────────────────────────────────────────

export interface InspectionSummaryPayload {
  readonly type: "inspection_summary";
  readonly filename: string;
  readonly rowCount: number;
  readonly colCount: number;
  readonly fileSizeBytes: number | null;
  readonly columns: ReadonlyArray<{
    readonly name: string;
    readonly dtype: string;
    readonly nullPct: number;
    readonly uniqueCount: number;
  }>;
}

export interface CleaningPlanPayload {
  readonly type: "cleaning_plan";
  readonly summary: string;
  readonly datasetId: string;
  readonly steps: ReadonlyArray<
    CleaningStep & { readonly confidence?: number; readonly rationale?: string }
  >;
  /** Set once the plan has been applied, so the card stays "Applied" across
   *  remounts (e.g. switching sessions away and back) instead of re-enabling. */
  readonly applied?: boolean;
}

export interface CleaningProgressPayload {
  readonly type: "cleaning_progress";
  readonly progress: number;
  readonly status: "running" | "complete" | "error";
  readonly message: string;
}

export interface ValidationSummaryPayload {
  readonly type: "validation_summary";
  readonly results: ReadonlyArray<{
    readonly stepDescription: string;
    readonly passed: boolean;
    readonly detail: string | null;
  }>;
  readonly overallPassed: boolean;
}

export interface CleaningResultsPayload {
  readonly type: "cleaning_results";
  readonly downloadUrl: string | null;
  readonly rowsBefore: number;
  readonly rowsAfter: number;
  readonly issuesResolved: number;
  readonly datasetId: string;
  /** The clean job behind these results — drives compare/revert/save-as-recipe. */
  readonly jobId?: string;
  readonly remediationApplied?: boolean;
  readonly unresolvableFlags?: readonly string[];
  /** Set once the user reverts this cleaning, so the card reflects it across remounts. */
  readonly reverted?: boolean;
  /** Set once saved as a recipe, so the card shows the saved state across remounts. */
  readonly savedRecipeName?: string;
}

export interface ErrorCardPayload {
  readonly type: "error";
  readonly title: string;
  readonly message: string;
  /**
   * Optional re-runnable action. When set, the card shows a "Try again" button
   * that re-dispatches `action`/`data` through the same card `onAction` handler
   * the original operation used, so retry reuses existing dispatch logic. Must
   * be serializable — it is persisted with the message.
   */
  readonly retry?: {
    readonly action: string;
    readonly data?: unknown;
    readonly label?: string;
  };
}

export interface DataOverviewPayload {
  readonly type: "data_overview";
  readonly rowCount: number;
  readonly colCount: number;
  readonly fileSizeBytes: number | null;
  readonly nullPercentage: number;
  readonly columnTypes: Record<string, number>;
}

export interface VisualizationPayload {
  readonly type: "visualization";
  readonly chart: ChartConfig;
  readonly description: string | null;
}

export interface ReportOutlinePayload {
  readonly type: "report_outline";
  readonly sections: ReadonlyArray<{
    readonly id: string;
    readonly title: string;
    readonly description: string;
  }>;
}

export interface ReportPreviewPayload {
  readonly type: "report_preview";
  readonly markdownContent: string;
  readonly tables: readonly TableResult[];
}

export interface ManipulationPreviewPayload {
  readonly type: "manipulation_preview";
  readonly command: string;
  readonly operations: ReadonlyArray<{
    readonly opType: string;
    readonly params: Record<string, unknown>;
    readonly description: string;
  }>;
  readonly previewBefore: ReadonlyArray<Record<string, unknown>>;
  readonly previewAfter: ReadonlyArray<Record<string, unknown>>;
  readonly affectedColumns: readonly string[];
  readonly affectedRowCount: number;
  readonly warnings: readonly string[];
  readonly confirmationRequired: boolean;
}

export interface ManipulationResultPayload {
  readonly type: "manipulation_result";
  readonly success: boolean;
  readonly snapshotId: string;
  readonly newRowCount: number;
  readonly newColCount: number;
  readonly columnsAdded: readonly string[];
  readonly columnsRemoved: readonly string[];
  readonly columnsRenamed: Readonly<Record<string, string>>;
  readonly sampleRows: ReadonlyArray<Record<string, unknown>>;
}

export interface DataPreviewPayload {
  readonly type: "data_preview";
  readonly datasetId: string;
  readonly columns: ReadonlyArray<{
    readonly name: string;
    readonly dtype: string;
    readonly nullPct: number;
    readonly hasIssues: boolean;
  }>;
  readonly rows: ReadonlyArray<Record<string, unknown>>;
  readonly totalRows: number;
  readonly totalPages: number;
  readonly page: number;
  readonly pageSize: number;
  readonly cellAnnotations: Readonly<
    Record<
      string,
      ReadonlyArray<{
        readonly type: string;
        readonly severity: string;
      }>
    >
  >;
}

export interface DataDictionaryPayload {
  readonly type: "data_dictionary";
  readonly datasetSummary: string;
  readonly columns: ReadonlyArray<{
    readonly name: string;
    readonly description: string;
    readonly businessMeaning: string;
    readonly dataType: string;
    readonly constraints: readonly string[];
    readonly notes: string;
  }>;
}

export interface ComparisonPayload {
  readonly type: "comparison";
  readonly datasets: {
    readonly before: { readonly id: string; readonly filename: string };
    readonly after: { readonly id: string; readonly filename: string };
  };
  readonly summary: {
    readonly rowsBefore: number;
    readonly rowsAfter: number;
    readonly rowsAdded: number;
    readonly rowsRemoved: number;
    readonly columnsAdded: number;
    readonly columnsRemoved: number;
    readonly cellsChanged: number;
  };
  readonly columns: {
    readonly added: readonly string[];
    readonly removed: readonly string[];
    readonly typeChanges: ReadonlyArray<{
      readonly column: string;
      readonly beforeType: string;
      readonly afterType: string;
    }>;
  };
  readonly statisticalDrift: ReadonlyArray<{
    readonly column: string;
    readonly beforeMean: number;
    readonly afterMean: number;
    readonly pctChange: number;
  }>;
  readonly sampleChanges: ReadonlyArray<{
    readonly row: number;
    readonly column: string;
    readonly before: unknown;
    readonly after: unknown;
  }>;
}

/** One checked precondition of a statistical test. `passed` is three-valued:
 *  null means the check could not be evaluated, which is not the same as
 *  passing. */
export interface AnalysisAssumption {
  readonly name: string;
  readonly passed: boolean | null;
  readonly detail: string;
  readonly statistic: number | null;
  readonly p_value: number | null;
}

export interface AnalysisEffectSize {
  readonly name: string;
  readonly value: number | null;
  readonly magnitude: string | null;
}

export interface AnalysisInterval {
  readonly low: number | null;
  readonly high: number | null;
  readonly level?: number;
  readonly of?: string;
}

/**
 * One row of a regression coefficient table, exactly as the API sends it.
 *
 * Two dialects reach the client. `analysis_regression` writes `std_err` /
 * `ci_low` / `ci_high` and names its statistic column `t` or `z`; the ARIMA
 * table in `analysis_timeseries` writes `std_error` / `ci95_low` / `ci95_high`.
 * Both are declared here and normalized once, in `@/lib/analysis-results`, so
 * that no component has to know which model produced its row.
 */
export interface AnalysisRawCoefficient {
  readonly term: string;
  readonly coefficient: number | null;
  readonly std_err?: number | null;
  readonly std_error?: number | null;
  readonly t?: number | null;
  readonly z?: number | null;
  readonly p_value: number | null;
  readonly p_value_is_bound?: boolean;
  readonly ci_low?: number | null;
  readonly ci_high?: number | null;
  readonly ci95_low?: number | null;
  readonly ci95_high?: number | null;
  readonly odds_ratio?: number | null;
  readonly or_ci_low?: number | null;
  readonly or_ci_high?: number | null;
  readonly irr?: number | null;
  readonly irr_ci_low?: number | null;
  readonly irr_ci_high?: number | null;
}

/** Variance inflation factor for one design term. */
export interface AnalysisVif {
  readonly term: string;
  readonly vif: number | null;
}

/** One step of an ARIMA forecast, with the prediction interval around it. */
export interface AnalysisForecastRow {
  readonly horizon: number;
  readonly date: string;
  readonly forecast: number | null;
  readonly std_error?: number | null;
  readonly ci95_low: number | null;
  readonly ci95_high: number | null;
}

/** The sampling design a survey estimate was made under. */
export interface AnalysisSurveyDesign {
  readonly weights?: string | null;
  readonly strata?: string | null;
  readonly cluster?: string | null;
  readonly sampling_fraction?: number | null;
  readonly variance_estimator?: string;
  readonly n?: number;
  readonly n_psu?: number;
  readonly n_strata?: number;
  readonly degrees_of_freedom?: number | null;
}

/**
 * The statistics payload attached to one executed operation.
 *
 * Additive by design: tiers 1-3 populate the first few keys, tier 4 adds
 * `coefficients`, tier 5 adds `forecast`, tier 6 adds the survey keys. Every
 * field is optional and most values may be null, because the backend reports a
 * statistic it could not compute as null rather than omitting it.
 */
export interface AnalysisStatistics {
  readonly test?: string;
  readonly model?: string;
  readonly statistic?: number | null;
  readonly p_value?: number | null;
  readonly effect_size?: AnalysisEffectSize;
  readonly confidence_interval?: AnalysisInterval;
  readonly assumptions?: readonly AnalysisAssumption[];

  // ── Tier 4: regression ──────────────────────────────────────────────────
  readonly outcome?: string;
  readonly regressors?: readonly string[];
  readonly coefficients?: readonly AnalysisRawCoefficient[];
  readonly reference_levels?: Readonly<Record<string, string>>;
  readonly statistic_column?: string;
  readonly standard_errors?: string;
  readonly vif?: readonly AnalysisVif[];
  readonly r_squared?: number | null;
  readonly adj_r_squared?: number | null;
  readonly f_statistic?: number | null;
  readonly f_p_value?: number | null;
  readonly rmse?: number | null;
  readonly pseudo_r_squared?: number | null;
  readonly pseudo_r_squared_kind?: string;
  readonly llr_p_value?: number | null;
  readonly base_rate?: number | null;
  readonly success_value?: string;
  readonly family?: string;
  readonly tau?: number | null;
  readonly aic?: number | null;
  readonly bic?: number | null;
  readonly df_model?: number | null;
  readonly df_resid?: number | null;

  // ── Tier 5: time series ─────────────────────────────────────────────────
  readonly forecast?: {
    readonly periods: number;
    readonly level: number;
    readonly rows: readonly AnalysisForecastRow[];
    readonly interval_meaning?: string;
  } | null;

  // ── Tier 6: survey ──────────────────────────────────────────────────────
  readonly estimate?: string;
  readonly n?: number | null;
  readonly design?: AnalysisSurveyDesign;
  readonly degrees_of_freedom?: number | null;
  readonly weighted_mean?: number | null;
  readonly unweighted_mean?: number | null;
  readonly weighted_total?: number | null;
  readonly unweighted_sum?: number | null;
  readonly standard_error?: number | null;
  readonly relative_standard_error?: number | null;
  readonly sum_of_weights?: number | null;
  readonly estimated_population?: number | null;
  readonly effective_sample_size?: number | null;
  readonly design_effect_kish?: number | null;
  readonly design_effect_design_based?: number | null;
  readonly weight_cv?: number | null;
  readonly reading?: string;
  readonly correction_factor?: number | null;
  readonly uncorrected_statistic?: number | null;
  readonly naive_weighted_statistic?: number | null;
  readonly naive_weighted_p_value?: number | null;
  readonly n_unweighted?: number | null;
  readonly dof?: number | null;
}

export interface AnalysisOperationRecord {
  readonly index: number;
  readonly op: string;
  readonly label: string;
  readonly params: Readonly<Record<string, unknown>>;
  readonly n: number;
  readonly n_excluded: number;
  readonly notes: readonly string[];
  readonly statistics: AnalysisStatistics;
}

/** One exported script, and the operations it could not express. */
export interface AnalysisCodeScript {
  readonly language: "python" | "r";
  readonly label: string;
  readonly source: string;
  /** Operations with no emitter in this dialect — the script is incomplete. */
  readonly incomplete: readonly string[];
}

// ── Normalized statistical views ────────────────────────────────────────────
// The API's payloads are a faithful transcript of what statsmodels produced,
// which means two spellings of "standard error" and three of "confidence
// bound". These types are what the components actually consume, produced once
// in `@/lib/analysis-results`.

/** A coefficient row after both API dialects have been reconciled. */
export interface AnalysisCoefficientRow {
  readonly term: string;
  /** The regressor this term belongs to, for a categorical indicator. */
  readonly variable: string | null;
  /** The level this indicator marks, for a categorical indicator. */
  readonly level: string | null;
  /**
   * True for the omitted baseline of a categorical, which carries no estimate.
   * The row exists because a coefficient table whose baseline is unnamed
   * cannot be interpreted: every indicator below it is a difference *from*
   * this level, and a reader who cannot see which level that is has no way to
   * read the numbers.
   */
  readonly isReference: boolean;
  readonly estimate: number | null;
  readonly stdError: number | null;
  readonly statistic: number | null;
  readonly pValue: number | null;
  /** True when the p-value is reported as a bound rather than a point. */
  readonly pValueIsBound: boolean;
  readonly ciLow: number | null;
  readonly ciHigh: number | null;
  /** The exponentiated view — odds ratio or incidence rate ratio — if any. */
  readonly ratio: {
    readonly value: number | null;
    readonly low: number | null;
    readonly high: number | null;
  } | null;
}

/** A named model-level statistic, formatted at render time. */
export interface AnalysisFitStatistic {
  readonly label: string;
  readonly value: number | null;
  readonly kind?: "integer" | "p_value";
}

export interface AnalysisRegressionView {
  readonly model: string | null;
  readonly outcome: string | null;
  /** "t" or "z" — whichever the fit actually reported. */
  readonly statisticLabel: string;
  /** "Odds ratio" or "Rate ratio (IRR)", when a ratio column exists. */
  readonly ratioLabel: string | null;
  readonly coefficients: readonly AnalysisCoefficientRow[];
  readonly referenceLevels: ReadonlyArray<{
    readonly variable: string;
    readonly level: string;
  }>;
  readonly fit: readonly AnalysisFitStatistic[];
  readonly standardErrors: string | null;
  readonly vif: readonly AnalysisVif[];
  readonly interval: AnalysisInterval | null;
}

/** One plotted period. `interval` is a recharts range value: `[low, high]`. */
export interface AnalysisForecastPoint {
  readonly date: string;
  readonly observed: number | null;
  readonly forecast: number | null;
  readonly interval: readonly [number, number] | null;
}

export interface AnalysisForecastView {
  readonly model: string | null;
  readonly level: number;
  readonly periods: number;
  readonly intervalMeaning: string | null;
  readonly points: readonly AnalysisForecastPoint[];
  /** False when every forecast step came back without bounds. */
  readonly hasInterval: boolean;
}

export interface AnalysisWeightedView {
  readonly estimate: string | null;
  readonly weightedLabel: string;
  readonly weighted: number | null;
  readonly unweightedLabel: string;
  readonly unweighted: number | null;
  readonly standardError: number | null;
  readonly relativeStandardError: number | null;
  readonly interval: AnalysisInterval | null;
  readonly respondents: number | null;
  readonly effectiveSampleSize: number | null;
  readonly designEffectKish: number | null;
  readonly designEffectDesignBased: number | null;
  readonly sumOfWeights: number | null;
  readonly estimatedPopulation: number | null;
  readonly reading: string | null;
  readonly design: AnalysisSurveyDesign | null;
  /** The Rao-Scott contrast, on a weighted crosstab only. */
  readonly raoScott: {
    readonly statistic: number | null;
    readonly uncorrected: number | null;
    readonly naive: number | null;
    readonly correctionFactor: number | null;
    readonly dof: number | null;
    readonly pValue: number | null;
    readonly naivePValue: number | null;
  } | null;
}

/** One executed operation, as the results card renders it. */
export interface AnalysisResultBlock {
  readonly index: number;
  readonly op: string;
  readonly label: string;
  readonly n: number;
  readonly nExcluded: number;
  readonly notes: readonly string[];
  readonly assumptions: readonly AnalysisAssumption[];
  readonly regression: AnalysisRegressionView | null;
  readonly forecast: AnalysisForecastView | null;
  readonly weighted: AnalysisWeightedView | null;
}

/** The computed statistics behind an answer, rendered rather than tabulated. */
export interface AnalysisResultsPayload {
  readonly type: "analysis_results";
  readonly blocks: readonly AnalysisResultBlock[];
}

/** The record behind a computed answer — what ran, over how many rows, under
 *  which assumptions, with which library versions. */
export interface AnalysisMethodsPayload {
  readonly type: "analysis_methods";
  readonly question: string;
  readonly dataset: {
    readonly filename: string | null;
    readonly rows: number;
    readonly columns: number;
  };
  readonly operations: readonly AnalysisOperationRecord[];
  readonly environment: {
    readonly python: string;
    readonly pandas: string;
    readonly numpy: string;
    readonly scipy: string;
  };
  readonly multipleComparisons: {
    readonly method: string;
    readonly controls: string;
    readonly n_tests: number;
    readonly tests: ReadonlyArray<{
      readonly label: string;
      readonly test: string;
      readonly p_value: number;
      readonly p_value_adjusted: number | null;
    }>;
  } | null;
  readonly methodsNote: string;
  /** Runnable scripts for the executed spec. Empty for a session recorded
   *  before code export existed — the note stands on its own without them. */
  readonly code: readonly AnalysisCodeScript[];
}

export interface HistoryPayload {
  readonly type: "history";
  readonly datasetId: string;
  readonly filename: string;
  readonly entries: ReadonlyArray<{
    readonly id: string;
    readonly type: string;
    readonly status: string;
    readonly progress: number;
    readonly createdAt: string | null;
    readonly completedAt: string | null;
    readonly summary?: {
      readonly rowsBefore: number | null;
      readonly rowsAfter: number | null;
      readonly cellsModified: number | null;
    };
  }>;
}

export type CardPayload =
  | InspectionSummaryPayload
  | CleaningPlanPayload
  | CleaningProgressPayload
  | ValidationSummaryPayload
  | CleaningResultsPayload
  | DataOverviewPayload
  | VisualizationPayload
  | ReportOutlinePayload
  | ReportPreviewPayload
  | ManipulationPreviewPayload
  | ManipulationResultPayload
  | DataPreviewPayload
  | DataDictionaryPayload
  | ComparisonPayload
  | HistoryPayload
  | AnalysisMethodsPayload
  | AnalysisResultsPayload
  | ErrorCardPayload;

/** Extended message type with optional card payloads. */
export interface ChatMessageV2 {
  readonly id: string;
  readonly role: MessageRole;
  readonly content: string;
  readonly card: CardPayload | null;
  readonly timestamp: string;
}
