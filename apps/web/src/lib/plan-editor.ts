/**
 * Editing a cleaning plan, as data.
 *
 * The review card is the last point at which a person can disagree with the
 * plan before it changes their file, so the edits have to be exact: a param
 * typed as text must reach the API as the number, list, or mapping the
 * executor reads, and a step the user did not touch must arrive byte-identical
 * to what was proposed.
 *
 * Everything here is pure and returns new values — no step, param bag, or
 * array is ever mutated in place, so React sees every change and an undo is a
 * matter of keeping the previous array.
 */

import type { CleaningStep } from "@/types";

/* ── The operation catalogue, as served by GET /cleaning/operations ──────── */

export type ParamKind =
  | "string"
  | "number"
  | "integer"
  | "enum"
  | "column"
  | "column_list"
  | "integer_list"
  | "mapping";

export interface ParamSpec {
  readonly name: string;
  readonly kind: ParamKind;
  readonly label: string;
  readonly help: string;
  readonly required: boolean;
  readonly default: unknown;
  readonly choices: readonly string[];
}

export interface OperationSpec {
  readonly name: string;
  readonly label: string;
  readonly group: string;
  readonly summary: string;
  readonly requiresColumn: boolean;
  readonly destructive: boolean;
  readonly requiresOneOf: readonly string[][];
  readonly params: readonly ParamSpec[];
}

export interface OperationCatalog {
  readonly groups: readonly string[];
  readonly operations: readonly OperationSpec[];
}

/** A step plus the fields only the UI cares about. */
export type EditableStep = CleaningStep & {
  readonly confidence?: number;
  readonly rationale?: string;
  /** Stable identity across reorders, so React keys survive a move. */
  readonly uid: string;
  /** Whether this step is included when the plan is applied. */
  readonly enabled: boolean;
  /** True for steps the user added themselves rather than the planner. */
  readonly addedByUser?: boolean;
  /** True once the user has changed anything about a proposed step. */
  readonly edited?: boolean;
};

export interface PlanIssue {
  readonly stepIndex: number;
  readonly field: "operation" | "column" | "params" | string;
  readonly message: string;
}

let uidCounter = 0;

/** A short unique id for a step row. Not persisted — identity within a card. */
export function nextUid(prefix = "step"): string {
  uidCounter += 1;
  return `${prefix}-${uidCounter}`;
}

/* ── Catalogue lookups ──────────────────────────────────────────────────── */

export function findOperation(
  catalog: OperationCatalog | null,
  operation: string,
): OperationSpec | undefined {
  return catalog?.operations.find((op) => op.name === operation);
}

/** Operations grouped for the "add step" picker, in the catalogue's own order. */
export function groupOperations(
  catalog: OperationCatalog | null,
): ReadonlyArray<{ group: string; operations: readonly OperationSpec[] }> {
  if (!catalog) return [];
  return catalog.groups
    .map((group) => ({
      group,
      operations: catalog.operations.filter((op) => op.group === group),
    }))
    .filter((entry) => entry.operations.length > 0);
}

/* ── Building steps ─────────────────────────────────────────────────────── */

/** Wrap the steps a plan arrived with for editing, all enabled. */
export function toEditableSteps(
  steps: ReadonlyArray<CleaningStep & { confidence?: number; rationale?: string }>,
): EditableStep[] {
  return steps.map((step) => ({
    ...step,
    params: { ...(step.params ?? {}) },
    uid: nextUid(),
    enabled: true,
  }));
}

/** A new step for `operation`, seeded from the catalogue's defaults. */
export function blankStep(spec: OperationSpec): EditableStep {
  const params: Record<string, unknown> = {};
  for (const param of spec.params) {
    if (param.default !== null && param.default !== undefined) {
      params[param.name] = structuredClone(param.default);
    }
  }
  return {
    operation: spec.name,
    column: null,
    params,
    description: spec.label,
    uid: nextUid("added"),
    enabled: true,
    addedByUser: true,
  };
}

/* ── Immutable step edits ───────────────────────────────────────────────── */

function markEdited(step: EditableStep): EditableStep {
  return step.addedByUser ? step : { ...step, edited: true };
}

export function updateStep(
  steps: readonly EditableStep[],
  uid: string,
  patch: Partial<EditableStep>,
): EditableStep[] {
  return steps.map((step) => (step.uid === uid ? markEdited({ ...step, ...patch }) : step));
}

/** Toggling inclusion is not an edit — the step itself is unchanged. */
export function toggleStep(steps: readonly EditableStep[], uid: string): EditableStep[] {
  return steps.map((step) => (step.uid === uid ? { ...step, enabled: !step.enabled } : step));
}

export function setStepParam(
  steps: readonly EditableStep[],
  uid: string,
  name: string,
  value: unknown,
): EditableStep[] {
  return steps.map((step) => {
    if (step.uid !== uid) return step;
    const params = { ...(step.params ?? {}) };
    // An empty optional param is absent, not empty — the executor reads
    // `params.get(name)` and treats a missing key as "use your default".
    if (value === undefined) {
      delete params[name];
    } else {
      params[name] = value;
    }
    return markEdited({ ...step, params });
  });
}

export function removeStep(steps: readonly EditableStep[], uid: string): EditableStep[] {
  return steps.filter((step) => step.uid !== uid);
}

export function insertStep(
  steps: readonly EditableStep[],
  step: EditableStep,
  at = steps.length,
): EditableStep[] {
  const index = Math.max(0, Math.min(at, steps.length));
  return [...steps.slice(0, index), step, ...steps.slice(index)];
}

/**
 * Move a step one position up or down.
 *
 * Order is not cosmetic: `clean_column_names` has to run before anything that
 * names a column, and a cap has to run before the outlier flag that follows it.
 */
export function moveStep(
  steps: readonly EditableStep[],
  uid: string,
  direction: -1 | 1,
): EditableStep[] {
  const from = steps.findIndex((step) => step.uid === uid);
  if (from < 0) return [...steps];
  const to = from + direction;
  if (to < 0 || to >= steps.length) return [...steps];
  const next = [...steps];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/* ── Param coercion ─────────────────────────────────────────────────────── */

/** Parse "0, 1, 4" or "0 1 4" into row indices, ignoring anything unparseable. */
export function parseIntegerList(raw: string): number[] {
  return raw
    .split(/[,\s]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .map((part) => Number(part))
    .filter((n) => Number.isInteger(n) && n >= 0);
}

/** Parse "NYC = New York" lines into the replacement mapping. */
export function parseMapping(raw: string): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const separator = line.indexOf("=");
    if (separator < 0) continue;
    const key = line.slice(0, separator).trim();
    if (!key) continue;
    mapping[key] = line.slice(separator + 1).trim();
  }
  return mapping;
}

export function formatMapping(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  return Object.entries(value as Record<string, unknown>)
    .map(([key, mapped]) => `${key} = ${String(mapped ?? "")}`)
    .join("\n");
}

export function formatIntegerList(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : "";
}

/**
 * Turn what the user typed into the value the executor expects.
 *
 * `undefined` means "leave this param out", which is different from an empty
 * string: an absent threshold falls back to the user's Settings default, while
 * an empty one would be read as a value.
 */
export function coerceParam(spec: ParamSpec, raw: unknown): unknown {
  if (raw === undefined || raw === null) return undefined;

  switch (spec.kind) {
    case "number":
    case "integer": {
      if (typeof raw === "number") return raw;
      const text = String(raw).trim();
      if (text === "") return undefined;
      const parsed = spec.kind === "integer" ? parseInt(text, 10) : Number(text);
      return Number.isFinite(parsed) ? parsed : undefined;
    }
    case "integer_list":
      return Array.isArray(raw) ? raw : parseIntegerList(String(raw));
    case "column_list": {
      if (Array.isArray(raw)) return raw.length > 0 ? raw : undefined;
      const names = String(raw)
        .split(",")
        .map((name) => name.trim())
        .filter(Boolean);
      return names.length > 0 ? names : undefined;
    }
    case "mapping":
      return typeof raw === "object" ? raw : parseMapping(String(raw));
    default: {
      const text = String(raw);
      return text === "" ? undefined : text;
    }
  }
}

/* ── Client-side validation ─────────────────────────────────────────────── */

/**
 * The same checks the API runs, so the card can mark a field as the user
 * leaves it rather than only on Apply. The server remains the authority —
 * this exists to make the feedback immediate, not to replace it.
 */
export function validateSteps(
  steps: readonly EditableStep[],
  catalog: OperationCatalog | null,
  columns: readonly string[],
): PlanIssue[] {
  const issues: PlanIssue[] = [];
  if (!catalog) return issues;

  // Mirrors the server's normalization: plans are usually written against
  // post-clean_column_names names while the file may still have dirty ones.
  const normalize = (name: string) =>
    name.replace(/\u00a0/g, " ").trim().replace(/ {2,}/g, " ");
  const available = new Set(columns.map(normalize));

  steps.forEach((step, index) => {
    const spec = findOperation(catalog, step.operation);
    if (!spec) {
      issues.push({
        stepIndex: index,
        field: "operation",
        message: `Unknown operation '${step.operation}'`,
      });
      return;
    }

    const params = step.params ?? {};

    if (spec.requiresColumn) {
      if (!step.column) {
        issues.push({
          stepIndex: index,
          field: "column",
          message: `${spec.label} needs a target column`,
        });
      } else if (!available.has(normalize(step.column))) {
        issues.push({
          stepIndex: index,
          field: "column",
          message: `Column '${step.column}' does not exist in the dataset`,
        });
      }
    }

    for (const param of spec.params) {
      const value = params[param.name];
      if (param.required && (value === undefined || value === null)) {
        issues.push({
          stepIndex: index,
          field: "params",
          message: `needs ${param.label.toLowerCase()}`,
        });
        continue;
      }
      // An empty required list or mapping passes the server's type check but
      // makes the step a silent no-op, which is worse than being told now.
      if (param.required && Array.isArray(value) && value.length === 0) {
        issues.push({
          stepIndex: index,
          field: "params",
          message: `${param.label} is empty, so this step would do nothing`,
        });
      }
      if (
        param.required &&
        param.kind === "mapping" &&
        value &&
        typeof value === "object" &&
        Object.keys(value as object).length === 0
      ) {
        issues.push({
          stepIndex: index,
          field: "params",
          message: `${param.label} is empty, so this step would do nothing`,
        });
      }
      if (param.kind === "enum" && typeof value === "string" && value !== "") {
        if (!param.choices.includes(value)) {
          issues.push({
            stepIndex: index,
            field: "params",
            message: `${param.label} must be one of ${param.choices.join(", ")}`,
          });
        }
      }
    }

    for (const group of spec.requiresOneOf) {
      if (group.every((name) => params[name] === undefined || params[name] === null)) {
        const labels = group
          .map((name) => spec.params.find((p) => p.name === name)?.label ?? name)
          .join(" or ");
        issues.push({
          stepIndex: index,
          field: "params",
          message: `Set ${labels}`,
        });
      }
    }

    // A step may target a column an earlier step creates.
    if (step.operation === "rename_column" && typeof params.new_name === "string") {
      available.add(normalize(params.new_name));
    }
    if (step.operation === "flag_extreme_outliers" || step.operation === "flag_contextual_fraud") {
      available.add(normalize(String(params.flag_column ?? "_flagged")));
    }
  });

  return issues;
}

/**
 * The parameters a step will actually run with, as short display pairs.
 *
 * A step's description is prose written when the plan was proposed; edit the
 * ceiling from 5000 to 250 and the sentence still says 5000. The row shows
 * these alongside it so what runs is visible even when the prose has gone
 * stale, and they are what lands in the audit trail either way.
 */
export function describeParams(
  step: EditableStep,
  spec: OperationSpec | undefined,
): ReadonlyArray<{ label: string; value: string }> {
  const params = step.params ?? {};
  return Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([name, value]) => ({
      label: spec?.params.find((p) => p.name === name)?.label ?? name,
      value: formatParamValue(value),
    }))
    .filter((entry) => entry.value !== "");
}

/** One param value, short enough to sit on a badge. */
export function formatParamValue(value: unknown): string {
  if (Array.isArray(value)) {
    if (value.length === 0) return "";
    const shown = value.slice(0, 4).join(", ");
    return value.length > 4 ? `${shown}, +${value.length - 4} more` : shown;
  }
  if (value && typeof value === "object") {
    const count = Object.keys(value as object).length;
    return count === 0 ? "" : `${count} replacement${count !== 1 ? "s" : ""}`;
  }
  return String(value);
}

/** Issues that belong to one step, keyed for a row to render. */
export function issuesForStep(issues: readonly PlanIssue[], index: number): PlanIssue[] {
  return issues.filter((issue) => issue.stepIndex === index);
}

/* ── Handing the plan to the API ────────────────────────────────────────── */

/** The enabled steps, stripped of every UI-only field. */
export function toApiSteps(steps: readonly EditableStep[]): CleaningStep[] {
  return steps
    .filter((step) => step.enabled)
    .map(({ operation, column, params, description }) => ({
      operation,
      column: column ?? null,
      params: { ...(params ?? {}) },
      description,
    }));
}

/** True when the user changed the plan in any way the API would see. */
export function planWasEdited(steps: readonly EditableStep[]): boolean {
  return steps.some((step) => step.addedByUser || step.edited || !step.enabled);
}
