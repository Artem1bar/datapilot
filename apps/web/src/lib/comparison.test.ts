import { describe, it, expect } from "vitest";
import { mapComparisonReport, type RawComparisonReport } from "./comparison";

const raw: RawComparisonReport = {
  summary: {
    rows_before: 15,
    rows_after: 13,
    rows_added: 0,
    rows_removed: 2,
    columns_added: 1,
    columns_removed: 0,
    cells_changed: 25,
  },
  columns: {
    added: ["quantity_flagged"],
    removed: [],
    type_changes: [{ column: "order_date", before_type: "object", after_type: "datetime64[us]" }],
  },
  statistical_drift: [
    { column: "unit_price", before_mean: 3350.2, after_mean: 18.9, pct_change: -99.4 },
  ],
  sample_changes: [{ row: 1, column: "customer_name", before: "  jane doe ", after: "jane doe" }],
  datasets: {
    before: { id: "ds-1", filename: "orders.csv" },
    after: { id: "job-1", filename: "orders_cleaned.csv" },
  },
};

describe("mapComparisonReport", () => {
  it("maps summary counters to camelCase", () => {
    const p = mapComparisonReport(raw);
    expect(p.summary).toEqual({
      rowsBefore: 15,
      rowsAfter: 13,
      rowsAdded: 0,
      rowsRemoved: 2,
      columnsAdded: 1,
      columnsRemoved: 0,
      cellsChanged: 25,
    });
  });

  it("maps column type changes", () => {
    const p = mapComparisonReport(raw);
    expect(p.columns.typeChanges).toEqual([
      { column: "order_date", beforeType: "object", afterType: "datetime64[us]" },
    ]);
    expect(p.columns.added).toEqual(["quantity_flagged"]);
  });

  it("maps statistical drift", () => {
    const p = mapComparisonReport(raw);
    expect(p.statisticalDrift[0]).toEqual({
      column: "unit_price",
      beforeMean: 3350.2,
      afterMean: 18.9,
      pctChange: -99.4,
    });
  });

  it("passes datasets and sample changes through", () => {
    const p = mapComparisonReport(raw);
    expect(p.type).toBe("comparison");
    expect(p.datasets.after.id).toBe("job-1");
    expect(p.sampleChanges).toHaveLength(1);
  });

  it("tolerates missing optional arrays", () => {
    const sparse = {
      ...raw,
      columns: { added: undefined, removed: undefined, type_changes: undefined },
      statistical_drift: undefined,
      sample_changes: undefined,
    } as unknown as RawComparisonReport;
    const p = mapComparisonReport(sparse);
    expect(p.columns.typeChanges).toEqual([]);
    expect(p.statisticalDrift).toEqual([]);
    expect(p.sampleChanges).toEqual([]);
  });
});
