// ── Dataset ──────────────────────────────────────────────────────────────────

export type DatasetStatus = "uploaded" | "profiling" | "ready" | "error";

export interface DatasetResponse {
  id: string;
  filename: string;
  r2_key: string;
  file_size_bytes: number | null;
  sheet_names: string[] | null;
  row_count: number | null;
  col_count: number | null;
  status: DatasetStatus;
  profile_json: Record<string, unknown> | null;
  created_at: string;
}

// ── Jobs ─────────────────────────────────────────────────────────────────────

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface JobResponse {
  id: string;
  dataset_id: string;
  type: string;
  status: JobStatus;
  progress: number;
  result_json: unknown;
  error_text: string | null;
  created_at: string;
  completed_at: string | null;
}

// ── Chat / AI ────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  charts?: ChartConfig[];
  tables?: TableResult[];
}

export interface ChatSessionResponse {
  id: string;
  dataset_id: string;
  messages_json: ChatMessage[];
  created_at: string;
  updated_at: string;
}

// ── Cleaning ─────────────────────────────────────────────────────────────────

export interface CleaningStep {
  operation: string;
  column: string | null;
  params: Record<string, unknown>;
  description: string;
}

// ── Charts / Visualization ───────────────────────────────────────────────────

export interface ChartConfig {
  chart_type: string;
  title: string;
  x_field: string;
  y_field: string;
  data: Record<string, unknown>[];
  options: Record<string, unknown>;
}

// ── Tables ───────────────────────────────────────────────────────────────────

export interface TableResult {
  columns: string[];
  rows: unknown[][];
  total_rows: number;
}

// ── API responses ────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
  status: number;
}

export interface UploadUrlResponse {
  upload_url: string;
  r2_key: string;
  dataset_id: string;
}

// ── Chat V2 (re-export) ─────────────────────────────────────────────────────

export type {
  MessageRole,
  WorkflowStepId,
  WorkflowStepStatus,
  WorkflowStep,
  WorkflowState,
  ActiveCleaningJob,
  Session,
  CardPayload,
  ChatMessageV2,
  AnalysisMethodsPayload,
  AnalysisOperationRecord,
  AnalysisAssumption,
  AnalysisStatistics,
  AnalysisEffectSize,
  AnalysisInterval,
  AnalysisRawCoefficient,
  AnalysisVif,
  AnalysisForecastRow,
  AnalysisSurveyDesign,
  AnalysisCodeScript,
  AnalysisCoefficientRow,
  AnalysisFitStatistic,
  AnalysisRegressionView,
  AnalysisForecastPoint,
  AnalysisForecastView,
  AnalysisWeightedView,
  AnalysisResultBlock,
  AnalysisResultsPayload,
  InspectionSummaryPayload,
  CleaningPlanPayload,
  CleaningProgressPayload,
  ValidationSummaryPayload,
  CleaningResultsPayload,
  DataOverviewPayload,
  VisualizationPayload,
  ReportOutlinePayload,
  ReportPreviewPayload,
  ManipulationPreviewPayload,
  ManipulationResultPayload,
  DataPreviewPayload,
  DataDictionaryPayload,
  ComparisonPayload,
  HistoryPayload,
  ErrorCardPayload,
} from "./chat";
