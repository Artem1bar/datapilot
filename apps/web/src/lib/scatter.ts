import type { ChartConfig } from "@/types";

/**
 * A scatter plot as the API describes it, parsed into something a component
 * can draw without trusting the payload.
 *
 * The chart config's `options` is an untyped record: the executor puts the
 * fit it computed, the color groups and the sampling facts in there, and the
 * planner path may send none of them. Everything here is checked before use,
 * so a chart with no fit draws points and a chart with a malformed fit draws
 * points — never a line the API did not compute.
 */

/** The API refuses a color column with more levels than this. */
export const MAX_COLOR_GROUPS = 12;

/** The group label the API gives points whose color column is missing. */
export const MISSING_GROUP = "(missing)";

export interface ScatterRequest {
  readonly x: string;
  readonly y: string;
  readonly colorBy: string | null;
  /** A numeric column that sizes the points: a bubble chart. */
  readonly size: string | null;
}

export interface ScatterPoint {
  readonly x: number;
  readonly y: number;
  readonly group: string | null;
  readonly size: number | null;
}

/** A question the chat can answer, and why it follows from this plot. */
export interface ScatterNextStep {
  readonly question: string;
  readonly why: string;
}

/** The reading the API computed from the fit: what it says, and what it does not. */
export interface ScatterInterpretation {
  readonly direction: string | null;
  readonly strength: string | null;
  readonly significant: boolean | null;
  readonly summary: readonly string[];
  readonly caveats: readonly string[];
  readonly nextSteps: readonly ScatterNextStep[];
}

/** The least-squares line the executor fitted on every complete row. */
export interface ScatterFit {
  readonly slope: number;
  readonly intercept: number;
  readonly rSquared: number | null;
  readonly pValue: number | null;
}

export interface ScatterView {
  readonly title: string;
  readonly xField: string;
  readonly yField: string;
  readonly points: readonly ScatterPoint[];
  readonly groupField: string | null;
  /** Legend order: named groups sorted, the missing bucket last. */
  readonly groups: readonly string[];
  /** Groups that exist in the data but have no point in the plotted sample. */
  readonly unplottedGroups: readonly string[];
  /** The column that sizes the points, and its range over every complete row. */
  readonly sizeField: string | null;
  readonly sizeRange: readonly [number, number] | null;
  readonly fit: ScatterFit | null;
  readonly interpretation: ScatterInterpretation | null;
  /** Rows the fit used, when the API said. */
  readonly n: number | null;
  readonly plotted: number;
  /** Complete rows available, when the API said — more than plotted if sampled. */
  readonly totalPoints: number | null;
  readonly sampled: boolean;
}

export interface ScatterSeries {
  /** Null for the single series of an uncolored plot. */
  readonly name: string | null;
  readonly points: readonly ScatterPoint[];
}

export interface ColumnChoice {
  readonly name: string;
  readonly dtype: string;
  readonly uniqueCount: number | null;
}

/** Which of a dataset's columns can be an axis, and which can color the points. */
export interface ScatterColumns {
  readonly numeric: readonly ColumnChoice[];
  readonly categorical: readonly ColumnChoice[];
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function optionalNumber(value: unknown): number | null {
  return isFiniteNumber(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toPoint(
  row: Record<string, unknown>,
  xField: string,
  yField: string,
): ScatterPoint | null {
  // The executor emits generic x/y keys; the planner path may name the fields.
  const x = "x" in row ? row.x : row[xField];
  const y = "y" in row ? row.y : row[yField];
  if (!isFiniteNumber(x) || !isFiniteNumber(y)) return null;
  const group = row.group === null || row.group === undefined ? null : String(row.group);
  return { x, y, group, size: isFiniteNumber(row.size) ? row.size : null };
}

function toRange(value: unknown): readonly [number, number] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [low, high] = value;
  return isFiniteNumber(low) && isFiniteNumber(high) ? [low, high] : null;
}

function toNextStep(value: unknown): ScatterNextStep | null {
  if (!isRecord(value)) return null;
  const { question, why } = value;
  return typeof question === "string" && typeof why === "string" ? { question, why } : null;
}

function toInterpretation(value: unknown): ScatterInterpretation | null {
  if (!isRecord(value) || !Array.isArray(value.summary)) return null;
  return {
    direction: typeof value.direction === "string" ? value.direction : null,
    strength: typeof value.strength === "string" ? value.strength : null,
    significant: typeof value.significant === "boolean" ? value.significant : null,
    summary: stringList(value.summary),
    caveats: stringList(value.caveats),
    nextSteps: Array.isArray(value.next_steps)
      ? value.next_steps
          .map(toNextStep)
          .filter((step): step is ScatterNextStep => step !== null)
      : [],
  };
}

function orderedGroups(labels: Iterable<string>): string[] {
  const distinct = new Set(labels);
  const named = [...distinct]
    .filter((label) => label !== MISSING_GROUP)
    .sort((a, b) => a.localeCompare(b));
  return distinct.has(MISSING_GROUP) ? [...named, MISSING_GROUP] : named;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function toFit(value: unknown): ScatterFit | null {
  if (!isRecord(value)) return null;
  if (!isFiniteNumber(value.slope) || !isFiniteNumber(value.intercept)) return null;
  return {
    slope: value.slope,
    intercept: value.intercept,
    rSquared: optionalNumber(value.r_squared),
    pValue: optionalNumber(value.p_value),
  };
}

/** Parse a scatter chart config, or null when it holds nothing to draw. */
export function toScatterView(config: ChartConfig): ScatterView | null {
  const xField = config.x_field || "x";
  const yField = config.y_field || "y";
  const points = (config.data ?? [])
    .filter(isRecord)
    .map((row) => toPoint(row, xField, yField))
    .filter((point): point is ScatterPoint => point !== null);
  if (points.length === 0) return null;

  const options = isRecord(config.options) ? config.options : {};
  const declared = stringList(options.groups);
  const seen = orderedGroups(
    points.flatMap((point) => (point.group === null ? [] : [point.group])),
  );
  const groups = [...declared, ...seen.filter((group) => !declared.includes(group))];

  return {
    title: config.title ?? "",
    xField,
    yField,
    points,
    groupField: typeof options.group_field === "string" ? options.group_field : null,
    groups,
    unplottedGroups: stringList(options.unplotted_groups).filter((group) =>
      groups.includes(group),
    ),
    sizeField: typeof options.size_field === "string" ? options.size_field : null,
    sizeRange: typeof options.size_field === "string" ? toRange(options.size_range) : null,
    fit: toFit(options.fit),
    interpretation: toInterpretation(options.interpretation),
    n: optionalNumber(options.n),
    plotted: points.length,
    totalPoints: optionalNumber(options.total_points),
    sampled: options.sampled === true,
  };
}

/**
 * The fitted line's endpoints across the plotted x range, or null when there
 * is no fit or no range to draw it over.
 */
export function fitSegment(
  view: ScatterView,
): readonly [{ x: number; y: number }, { x: number; y: number }] | null {
  if (!view.fit) return null;
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const point of view.points) {
    if (point.x < min) min = point.x;
    if (point.x > max) max = point.x;
  }
  if (min === max) return null;
  const { slope, intercept } = view.fit;
  return [
    { x: min, y: slope * min + intercept },
    { x: max, y: slope * max + intercept },
  ];
}

/** The points split by group in legend order, or one unnamed series. */
export function scatterSeries(view: ScatterView): readonly ScatterSeries[] {
  if (view.groups.length === 0) return [{ name: null, points: view.points }];
  return view.groups.map((name) => ({
    name,
    points: view.points.filter((point) => point.group === name),
  }));
}

// pandas dtype names for columns that can be an axis. Booleans are left out:
// True/False on an axis is a bar chart pretending to be a scatter.
const NUMERIC_DTYPE = /^(u?int|float|Int|UInt|Float)\d*$/;
const TIME_DTYPE = /datetime|timedelta|period/i;

/** Sort a dataset's profiled columns into axis candidates and color candidates. */
export function scatterColumns(profile: unknown): ScatterColumns {
  const columns = isRecord(profile) && isRecord(profile.columns) ? profile.columns : null;
  if (!columns) return { numeric: [], categorical: [] };

  const choices: ColumnChoice[] = Object.entries(columns).flatMap(([name, info]) =>
    isRecord(info)
      ? [
          {
            name,
            dtype: typeof info.dtype === "string" ? info.dtype : "unknown",
            uniqueCount: optionalNumber(info.unique_count),
          },
        ]
      : [],
  );
  // The profile arrives in JSONB key order (shorter keys first), which no
  // reader can predict; by name is the order a select list is scanned in.
  const byName = [...choices].sort((a, b) => a.name.localeCompare(b.name));
  return {
    numeric: byName.filter((column) => NUMERIC_DTYPE.test(column.dtype)),
    categorical: byName.filter(
      (column) =>
        !TIME_DTYPE.test(column.dtype) &&
        column.uniqueCount !== null &&
        column.uniqueCount >= 2 &&
        column.uniqueCount <= MAX_COLOR_GROUPS,
    ),
  };
}

/** The request in words — the same sentence the API records as the question. */
export function describeScatterRequest(request: ScatterRequest): string {
  let description = `Scatter plot of ${request.y} against ${request.x}`;
  if (request.colorBy) description += `, colored by ${request.colorBy}`;
  if (request.size) description += `, sized by ${request.size}`;
  return description;
}
