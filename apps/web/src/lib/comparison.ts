import type { ComparisonPayload } from "@/types";

/**
 * Raw comparison report from the API (snake_case), as returned by
 * `GET /cleaning/{job_id}/comparison` and `POST /datasets/{id}/compare/{other}`.
 */
export interface RawComparisonReport {
  summary: {
    rows_before: number;
    rows_after: number;
    rows_added: number;
    rows_removed: number;
    columns_added: number;
    columns_removed: number;
    cells_changed: number;
  };
  columns: {
    added: string[];
    removed: string[];
    type_changes: Array<{ column: string; before_type: string; after_type: string }>;
  };
  statistical_drift: Array<{
    column: string;
    before_mean: number;
    after_mean: number;
    pct_change: number;
  }>;
  sample_changes: Array<{ row: number; column: string; before: unknown; after: unknown }>;
  datasets: {
    before: { id: string; filename: string };
    after: { id: string; filename: string };
  };
}

/** Map the API's snake_case comparison report to the ComparisonCard payload. */
export function mapComparisonReport(raw: RawComparisonReport): ComparisonPayload {
  return {
    type: "comparison",
    datasets: raw.datasets,
    summary: {
      rowsBefore: raw.summary.rows_before,
      rowsAfter: raw.summary.rows_after,
      rowsAdded: raw.summary.rows_added,
      rowsRemoved: raw.summary.rows_removed,
      columnsAdded: raw.summary.columns_added,
      columnsRemoved: raw.summary.columns_removed,
      cellsChanged: raw.summary.cells_changed,
    },
    columns: {
      added: raw.columns.added ?? [],
      removed: raw.columns.removed ?? [],
      typeChanges: (raw.columns.type_changes ?? []).map((tc) => ({
        column: tc.column,
        beforeType: tc.before_type,
        afterType: tc.after_type,
      })),
    },
    statisticalDrift: (raw.statistical_drift ?? []).map((d) => ({
      column: d.column,
      beforeMean: d.before_mean,
      afterMean: d.after_mean,
      pctChange: d.pct_change,
    })),
    sampleChanges: raw.sample_changes ?? [],
  };
}
