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
  readonly steps: ReadonlyArray<CleaningStep & { readonly confidence?: number }>;
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
  readonly remediationApplied?: boolean;
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
  readonly cellAnnotations: Readonly<Record<string, ReadonlyArray<{
    readonly type: string;
    readonly severity: string;
  }>>>;
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
  | HistoryPayload;

/** Extended message type with optional card payloads. */
export interface ChatMessageV2 {
  readonly id: string;
  readonly role: MessageRole;
  readonly content: string;
  readonly card: CardPayload | null;
  readonly timestamp: string;
}
