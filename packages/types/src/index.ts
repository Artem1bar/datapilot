// ─── User ───────────────────────────────────────────────────
export interface User {
  id: string;
  clerk_id: string;
  email: string;
  plan: "free" | "pro" | "academic";
  credits_remaining: number;
  created_at: string;
}

// ─── Dataset ────────────────────────────────────────────────
export interface Dataset {
  id: string;
  user_id: string;
  filename: string;
  r2_key: string;
  file_size_bytes: number | null;
  sheet_names: string[] | null;
  row_count: number | null;
  col_count: number | null;
  status: "uploaded" | "profiled" | "cleaned" | "error";
  profile_json: DatasetProfile | null;
  created_at: string;
}

// ─── Job ────────────────────────────────────────────────────
export interface Job {
  id: string;
  dataset_id: string;
  user_id: string;
  type: "profile" | "clean" | "analyze" | "export";
  status: "pending" | "running" | "complete" | "failed";
  progress: number;
  input_json: Record<string, unknown> | null;
  result_json: Record<string, unknown> | null;
  error_text: string | null;
  celery_task_id: string | null;
  created_at: string;
  completed_at: string | null;
}

// ─── Data Profiling ─────────────────────────────────────────
export interface ColumnProfile {
  name: string;
  dtype_detected: "numeric" | "datetime" | "categorical" | "text" | "mixed";
  null_count: number;
  null_pct: number;
  unique_count: number;
  sample_values: unknown[];
  issues: string[];
  suggested_fixes: CleaningStep[];
}

export interface DatasetProfile {
  row_count: number;
  col_count: number;
  duplicate_row_count: number;
  columns: ColumnProfile[];
  global_issues: string[];
}

// ─── Cleaning ───────────────────────────────────────────────
export interface CleaningStep {
  id: string;
  type:
    | "normalize_dates"
    | "unify_categories"
    | "remove_duplicates"
    | "handle_nulls"
    | "fix_types"
    | "strip_whitespace"
    | "custom";
  column: string | null;
  description: string;
  before_sample: unknown[];
  after_sample: unknown[];
  confidence: number;
  accepted: boolean;
}

export interface CleaningPlan {
  dataset_id: string;
  steps: CleaningStep[];
  summary: string;
}

// ─── Analysis ───────────────────────────────────────────────
export interface ChartConfig {
  type: "bar" | "line" | "histogram" | "pie" | "scatter" | "box";
  title: string;
  x_key: string;
  y_key: string | null;
  color_key: string | null;
  data: Record<string, unknown>[];
  insights: string;
}

export interface TableResult {
  title: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
}

export interface AnalysisResult {
  job_id: string;
  chart_configs: ChartConfig[];
  tables: TableResult[];
  narrative: string;
  sql_equivalent: string | null;
}

// ─── Job Updates (WebSocket) ────────────────────────────────
export interface JobUpdate {
  job_id: string;
  status: string;
  progress: number;
  message: string | null;
  result: AnalysisResult | CleaningPlan | null;
}

// ─── API Request/Response Types ─────────────────────────────
export interface UploadUrlResponse {
  upload_url: string;
  dataset_id: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  result?: AnalysisResult;
}

export interface ChatSession {
  id: string;
  dataset_id: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}
