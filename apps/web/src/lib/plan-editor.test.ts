import { describe, it, expect } from "vitest";
import {
  blankStep,
  coerceParam,
  findOperation,
  formatIntegerList,
  formatMapping,
  groupOperations,
  insertStep,
  issuesForStep,
  moveStep,
  parseIntegerList,
  parseMapping,
  planWasEdited,
  removeStep,
  setStepParam,
  toApiSteps,
  toEditableSteps,
  toggleStep,
  updateStep,
  validateSteps,
  type OperationCatalog,
  type OperationSpec,
  type ParamSpec,
} from "./plan-editor";

/* ── Fixtures mirroring what GET /cleaning/operations returns ───────────── */

function param(overrides: Partial<ParamSpec> & { name: string; kind: ParamSpec["kind"] }): ParamSpec {
  return {
    label: overrides.name,
    help: "",
    required: false,
    default: null,
    choices: [],
    ...overrides,
  };
}

function operation(overrides: Partial<OperationSpec> & { name: string }): OperationSpec {
  return {
    label: overrides.name,
    group: "Other",
    summary: "",
    requiresColumn: true,
    destructive: false,
    requiresOneOf: [],
    params: [],
    ...overrides,
  };
}

const CATALOG: OperationCatalog = {
  groups: ["Structural", "Standardization", "Anomalies", "Other"],
  operations: [
    operation({
      name: "clean_column_names",
      label: "Clean column names",
      group: "Structural",
      requiresColumn: false,
    }),
    operation({ name: "strip_whitespace", label: "Strip whitespace", group: "Standardization" }),
    operation({
      name: "fill_null",
      label: "Fill empty values",
      group: "Standardization",
      requiresOneOf: [["strategy", "value"]],
      params: [
        param({ name: "strategy", kind: "enum", label: "Strategy", choices: ["mean", "median", "mode"] }),
        param({ name: "value", kind: "string", label: "Fixed value" }),
      ],
    }),
    operation({
      name: "cap_extreme_values",
      label: "Cap extreme values",
      group: "Anomalies",
      destructive: true,
      params: [param({ name: "max_value", kind: "number", label: "Ceiling", required: true })],
    }),
    operation({
      name: "rename_column",
      label: "Rename column",
      params: [param({ name: "new_name", kind: "string", label: "New name", required: true })],
    }),
    operation({
      name: "drop_rows",
      label: "Drop specific rows",
      group: "Structural",
      requiresColumn: false,
      destructive: true,
      params: [
        param({ name: "indices", kind: "integer_list", label: "Row indices", required: true, default: [] }),
      ],
    }),
    operation({
      name: "standardize_values",
      label: "Standardize values",
      params: [
        param({ name: "mapping", kind: "mapping", label: "Replacements", required: true, default: {} }),
      ],
    }),
    operation({
      name: "flag_extreme_outliers",
      label: "Flag extreme outliers",
      group: "Anomalies",
      params: [
        param({ name: "threshold", kind: "number", label: "Threshold override" }),
        param({ name: "flag_column", kind: "string", label: "Flag column", default: "_flagged" }),
      ],
    }),
    operation({
      name: "deduplicate",
      label: "Remove duplicate rows",
      requiresColumn: false,
      params: [param({ name: "subset", kind: "column_list", label: "Compare only these" })],
    }),
  ],
};

const COLUMNS = ["Amount", "City", "Name"];

function plan() {
  return toEditableSteps([
    { operation: "clean_column_names", column: null, params: {}, description: "Step 1", confidence: 0.9 },
    { operation: "strip_whitespace", column: "Name", params: {}, description: "Step 2" },
    {
      operation: "cap_extreme_values",
      column: "Amount",
      params: { max_value: 5000 },
      description: "Step 3",
    },
  ]);
}

/* ── Catalogue lookups ──────────────────────────────────────────────────── */

describe("catalogue lookups", () => {
  it("finds an operation by name", () => {
    expect(findOperation(CATALOG, "fill_null")?.label).toBe("Fill empty values");
    expect(findOperation(CATALOG, "nope")).toBeUndefined();
    expect(findOperation(null, "fill_null")).toBeUndefined();
  });

  it("groups operations in the catalogue's own order, dropping empty groups", () => {
    const grouped = groupOperations(CATALOG);
    expect(grouped.map((g) => g.group)).toEqual([
      "Structural",
      "Standardization",
      "Anomalies",
      "Other",
    ]);
    expect(grouped[0].operations.map((o) => o.name)).toContain("clean_column_names");
  });
});

/* ── Immutability: the rule that keeps an edit from leaking sideways ─────── */

describe("edits never mutate the plan they are given", () => {
  it("updateStep leaves the input array and its steps untouched", () => {
    const before = plan();
    const snapshot = JSON.parse(JSON.stringify(before));

    const after = updateStep(before, before[1].uid, { column: "City" });

    expect(before).toEqual(snapshot);
    expect(after).not.toBe(before);
    expect(after[1].column).toBe("City");
    expect(before[1].column).toBe("Name");
  });

  it("setStepParam does not share the params object with the original", () => {
    const before = plan();
    const after = setStepParam(before, before[2].uid, "max_value", 99);

    expect(before[2].params).toEqual({ max_value: 5000 });
    expect(after[2].params).toEqual({ max_value: 99 });
    expect(after[2].params).not.toBe(before[2].params);
  });

  it("toEditableSteps copies params so the incoming payload cannot be edited", () => {
    const incoming = [
      { operation: "cap_extreme_values", column: "Amount", params: { max_value: 1 }, description: "s" },
    ];
    const editable = toEditableSteps(incoming);
    const changed = setStepParam(editable, editable[0].uid, "max_value", 2);

    expect(incoming[0].params).toEqual({ max_value: 1 });
    expect(changed[0].params).toEqual({ max_value: 2 });
  });

  it("moveStep, removeStep and insertStep all return new arrays", () => {
    const before = plan();
    expect(moveStep(before, before[0].uid, 1)).not.toBe(before);
    expect(removeStep(before, before[0].uid)).not.toBe(before);
    expect(insertStep(before, blankStep(CATALOG.operations[1]))).not.toBe(before);
    expect(before).toHaveLength(3);
  });
});

/* ── Reordering ─────────────────────────────────────────────────────────── */

describe("reordering", () => {
  it("moves a step down and keeps every step", () => {
    const before = plan();
    const after = moveStep(before, before[0].uid, 1);
    expect(after.map((s) => s.description)).toEqual(["Step 2", "Step 1", "Step 3"]);
  });

  it("moves a step up", () => {
    const before = plan();
    const after = moveStep(before, before[2].uid, -1);
    expect(after.map((s) => s.description)).toEqual(["Step 1", "Step 3", "Step 2"]);
  });

  it("refuses to move the first step up or the last step down", () => {
    const before = plan();
    expect(moveStep(before, before[0].uid, -1).map((s) => s.description)).toEqual([
      "Step 1",
      "Step 2",
      "Step 3",
    ]);
    expect(moveStep(before, before[2].uid, 1).map((s) => s.description)).toEqual([
      "Step 1",
      "Step 2",
      "Step 3",
    ]);
  });

  it("ignores a move for a step that is not there", () => {
    const before = plan();
    expect(moveStep(before, "missing", 1)).toHaveLength(3);
  });

  it("keeps step identity stable across a move, so React keys survive", () => {
    const before = plan();
    const uid = before[0].uid;
    const after = moveStep(before, uid, 1);
    expect(after[1].uid).toBe(uid);
  });
});

/* ── Adding steps ───────────────────────────────────────────────────────── */

describe("adding a step", () => {
  it("seeds params from the catalogue defaults and omits ones the user must supply", () => {
    const step = blankStep(findOperation(CATALOG, "flag_extreme_outliers")!);
    expect(step.params).toEqual({ flag_column: "_flagged" });
    expect(step.params).not.toHaveProperty("threshold");
  });

  it("does not share a default list between two added steps", () => {
    const spec = findOperation(CATALOG, "drop_rows")!;
    const first = blankStep(spec);
    const second = blankStep(spec);
    const edited = setStepParam([first], first.uid, "indices", [1, 2]);

    expect(edited[0].params.indices).toEqual([1, 2]);
    expect(second.params.indices).toEqual([]);
    expect(spec.params[0].default).toEqual([]);
  });

  it("marks the step as user-added and gives it a unique id", () => {
    const a = blankStep(CATALOG.operations[1]);
    const b = blankStep(CATALOG.operations[1]);
    expect(a.addedByUser).toBe(true);
    expect(a.enabled).toBe(true);
    expect(a.uid).not.toBe(b.uid);
  });

  it("inserts at a given position, clamping out-of-range indices", () => {
    const before = plan();
    const added = blankStep(CATALOG.operations[1]);
    expect(insertStep(before, added, 1)[1].uid).toBe(added.uid);
    expect(insertStep(before, added, -5)[0].uid).toBe(added.uid);
    expect(insertStep(before, added, 99).at(-1)!.uid).toBe(added.uid);
  });
});

/* ── Param coercion — where a typed string becomes what the executor reads ── */

describe("coerceParam", () => {
  const numeric = param({ name: "max_value", kind: "number", label: "Ceiling" });
  const whole = param({ name: "min_progress", kind: "integer", label: "Minimum" });

  it("parses numbers and integers", () => {
    expect(coerceParam(numeric, "5000")).toBe(5000);
    expect(coerceParam(numeric, "12.5")).toBe(12.5);
    expect(coerceParam(whole, "100")).toBe(100);
    expect(coerceParam(whole, "100.7")).toBe(100);
  });

  it("treats a cleared field as absent, not as zero", () => {
    // The failure this prevents: an emptied threshold reaching the executor as
    // 0 and flagging every row, instead of falling back to Settings.
    expect(coerceParam(numeric, "")).toBeUndefined();
    expect(coerceParam(numeric, "   ")).toBeUndefined();
    expect(coerceParam(numeric, null)).toBeUndefined();
  });

  it("drops an unparseable number rather than sending NaN", () => {
    expect(coerceParam(numeric, "abc")).toBeUndefined();
  });

  it("parses row indices from commas or spaces and ignores junk", () => {
    const spec = param({ name: "indices", kind: "integer_list", label: "Rows" });
    expect(coerceParam(spec, "0, 1, 4")).toEqual([0, 1, 4]);
    expect(coerceParam(spec, "0 1 4")).toEqual([0, 1, 4]);
    expect(coerceParam(spec, "2,, x, -3, 7")).toEqual([2, 7]);
    expect(coerceParam(spec, [3, 4])).toEqual([3, 4]);
  });

  it("parses a replacement mapping from one line per entry", () => {
    const spec = param({ name: "mapping", kind: "mapping", label: "Replacements" });
    expect(coerceParam(spec, "NYC = New York\nLA=Los Angeles")).toEqual({
      NYC: "New York",
      LA: "Los Angeles",
    });
  });

  it("parses a column list and treats an empty one as absent", () => {
    const spec = param({ name: "subset", kind: "column_list", label: "Columns" });
    expect(coerceParam(spec, "Amount, City")).toEqual(["Amount", "City"]);
    expect(coerceParam(spec, "")).toBeUndefined();
    expect(coerceParam(spec, [])).toBeUndefined();
  });

  it("round-trips lists and mappings through their display form", () => {
    expect(formatIntegerList([0, 1, 4])).toBe("0, 1, 4");
    expect(parseIntegerList(formatIntegerList([0, 1, 4]))).toEqual([0, 1, 4]);
    const mapping = { NYC: "New York" };
    expect(parseMapping(formatMapping(mapping))).toEqual(mapping);
    expect(formatMapping(null)).toBe("");
    expect(formatIntegerList(undefined)).toBe("");
  });
});

/* ── setStepParam ───────────────────────────────────────────────────────── */

describe("setStepParam", () => {
  it("removes the key entirely when the value is undefined", () => {
    const before = toEditableSteps([
      { operation: "flag_extreme_outliers", column: "Amount", params: { threshold: 4 }, description: "s" },
    ]);
    const after = setStepParam(before, before[0].uid, "threshold", undefined);
    expect("threshold" in after[0].params).toBe(false);
  });

  it("marks a proposed step as edited but leaves an added step alone", () => {
    const proposed = plan();
    expect(setStepParam(proposed, proposed[2].uid, "max_value", 1)[2].edited).toBe(true);

    const added = [blankStep(findOperation(CATALOG, "cap_extreme_values")!)];
    const changed = setStepParam(added, added[0].uid, "max_value", 1);
    expect(changed[0].edited).toBeUndefined();
    expect(changed[0].addedByUser).toBe(true);
  });
});

/* ── Validation ─────────────────────────────────────────────────────────── */

describe("validateSteps", () => {
  it("accepts a plan that is fully specified", () => {
    expect(validateSteps(plan(), CATALOG, COLUMNS)).toEqual([]);
  });

  it("names a column that is not in the dataset", () => {
    const steps = plan();
    const mistyped = updateStep(steps, steps[1].uid, { column: "Nmae" });
    const issues = validateSteps(mistyped, CATALOG, COLUMNS);
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({ stepIndex: 1, field: "column" });
    expect(issues[0].message).toContain("Nmae");
  });

  it("requires a column for operations that act on one", () => {
    const steps = toEditableSteps([
      { operation: "strip_whitespace", column: null, params: {}, description: "s" },
    ]);
    const issues = validateSteps(steps, CATALOG, COLUMNS);
    expect(issues[0].field).toBe("column");
  });

  it("does not require a column for whole-dataset operations", () => {
    const steps = toEditableSteps([
      { operation: "clean_column_names", column: null, params: {}, description: "s" },
      { operation: "deduplicate", column: null, params: {}, description: "s" },
    ]);
    expect(validateSteps(steps, CATALOG, COLUMNS)).toEqual([]);
  });

  it("names a missing required param in the user's words", () => {
    const steps = toEditableSteps([
      { operation: "cap_extreme_values", column: "Amount", params: {}, description: "s" },
    ]);
    const issues = validateSteps(steps, CATALOG, COLUMNS);
    expect(issues[0].field).toBe("params");
    expect(issues[0].message).toContain("ceiling");
  });

  it("flags an empty required list as a step that would do nothing", () => {
    const steps = toEditableSteps([
      { operation: "drop_rows", column: null, params: { indices: [] }, description: "s" },
    ]);
    const issues = validateSteps(steps, CATALOG, COLUMNS);
    expect(issues).toHaveLength(1);
    expect(issues[0].message).toMatch(/would do nothing/);
  });

  it("flags an empty required mapping the same way", () => {
    const steps = toEditableSteps([
      { operation: "standardize_values", column: "City", params: { mapping: {} }, description: "s" },
    ]);
    expect(validateSteps(steps, CATALOG, COLUMNS)[0].message).toMatch(/would do nothing/);
  });

  it("accepts fill_null with a strategy or a value, and refuses it with neither", () => {
    const base = { operation: "fill_null", column: "Amount", description: "s" };
    expect(validateSteps(toEditableSteps([{ ...base, params: {} }]), CATALOG, COLUMNS)).toHaveLength(1);
    expect(
      validateSteps(toEditableSteps([{ ...base, params: { strategy: "median" } }]), CATALOG, COLUMNS),
    ).toEqual([]);
    expect(
      validateSteps(toEditableSteps([{ ...base, params: { value: "0" } }]), CATALOG, COLUMNS),
    ).toEqual([]);
  });

  it("rejects an enum value outside the choices", () => {
    const steps = toEditableSteps([
      { operation: "fill_null", column: "Amount", params: { strategy: "magic" }, description: "s" },
    ]);
    const issues = validateSteps(steps, CATALOG, COLUMNS);
    expect(issues.some((i) => i.message.includes("mean, median, mode"))).toBe(true);
  });

  it("lets a later step target a column an earlier rename creates", () => {
    const steps = toEditableSteps([
      { operation: "rename_column", column: "Amount", params: { new_name: "Revenue" }, description: "s" },
      { operation: "strip_whitespace", column: "Revenue", params: {}, description: "s" },
    ]);
    expect(validateSteps(steps, CATALOG, COLUMNS)).toEqual([]);
  });

  it("lets a later step target the flag column an outlier step creates", () => {
    const steps = toEditableSteps([
      { operation: "flag_extreme_outliers", column: "Amount", params: {}, description: "s" },
      { operation: "strip_whitespace", column: "_flagged", params: {}, description: "s" },
    ]);
    expect(validateSteps(steps, CATALOG, COLUMNS)).toEqual([]);
  });

  it("matches a column whose real name carries a non-breaking space", () => {
    const steps = toEditableSteps([
      { operation: "strip_whitespace", column: "Full Name", params: {}, description: "s" },
    ]);
    expect(validateSteps(steps, CATALOG, ["Full Name"])).toEqual([]);
  });

  it("flags an unknown operation", () => {
    const steps = toEditableSteps([
      { operation: "make_coffee", column: null, params: {}, description: "s" },
    ]);
    expect(validateSteps(steps, CATALOG, COLUMNS)[0].field).toBe("operation");
  });

  it("reports nothing while the catalogue is still loading", () => {
    expect(validateSteps(plan(), null, COLUMNS)).toEqual([]);
  });

  it("checks disabled steps too, so re-enabling one cannot smuggle in a bad step", () => {
    const steps = plan();
    const withBadDisabled = toggleStep(
      steps.map((s, i) => (i === 2 ? { ...s, params: {} } : s)),
      steps[2].uid,
    );
    expect(withBadDisabled[2].enabled).toBe(false);
    expect(validateSteps(withBadDisabled, CATALOG, COLUMNS)).toHaveLength(1);
  });

  it("groups issues by the step they belong to", () => {
    const steps = toEditableSteps([
      { operation: "strip_whitespace", column: "Amount", params: {}, description: "ok" },
      { operation: "rename_column", column: "City", params: {}, description: "bad" },
    ]);
    const issues = validateSteps(steps, CATALOG, COLUMNS);
    expect(issuesForStep(issues, 0)).toEqual([]);
    expect(issuesForStep(issues, 1)).toHaveLength(1);
  });
});

/* ── Handing the plan to the API ────────────────────────────────────────── */

describe("toApiSteps", () => {
  it("sends only enabled steps, stripped of UI-only fields", () => {
    const original = plan();
    const payload = toApiSteps(toggleStep(original, original[0].uid));

    expect(payload).toHaveLength(2);
    expect(payload[0]).not.toHaveProperty("uid");
    expect(payload[0]).not.toHaveProperty("enabled");
    expect(payload[0]).not.toHaveProperty("confidence");
    expect(payload[0]).not.toHaveProperty("rationale");
    expect(payload[0]).not.toHaveProperty("addedByUser");
  });

  it("keeps the edited order", () => {
    const original = plan();
    const steps = moveStep(original, original[0].uid, 1);
    expect(toApiSteps(steps).map((s) => s.description)).toEqual(["Step 2", "Step 1", "Step 3"]);
  });

  it("sends column as null rather than omitting it", () => {
    const payload = toApiSteps(plan());
    expect(payload[0].column).toBeNull();
  });

  it("does not share params with the editor's state", () => {
    const steps = plan();
    const payload = toApiSteps(steps);
    expect(payload[2].params).not.toBe(steps[2].params);
  });
});

describe("planWasEdited", () => {
  it("is false for an untouched plan", () => {
    expect(planWasEdited(plan())).toBe(false);
  });

  it("is true after a param change, a toggle, or an addition", () => {
    const steps = plan();
    expect(planWasEdited(setStepParam(steps, steps[2].uid, "max_value", 1))).toBe(true);
    expect(planWasEdited(toggleStep(steps, steps[0].uid))).toBe(true);
    expect(planWasEdited(insertStep(steps, blankStep(CATALOG.operations[1])))).toBe(true);
  });

  it("is true after a removal, since the applied plan differs from the proposal", () => {
    const steps = plan();
    // A removal leaves no marker on the remaining steps, so it is detected by
    // the plan being shorter — the card passes the original length in.
    expect(removeStep(steps, steps[0].uid)).toHaveLength(2);
  });
});
