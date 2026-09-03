import { useMemo } from "react";
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { formatStatistic } from "@/lib/analysis-format";
import {
  MISSING_GROUP,
  fitSegment,
  scatterSeries,
  toScatterView,
  type ScatterPoint,
  type ScatterView,
} from "@/lib/scatter";
import type { ChartConfig } from "@/types";
import { BRAND_GOLD, BRAND_PURPLE, GROUP_COLORS } from "./palette";

/**
 * Points on two numeric axes, with the line the executor fitted.
 *
 * Both axes are numeric on purpose. recharts defaults an axis to categorical,
 * which spaces the distinct x values evenly in the order they arrive — a plot
 * of 0, 1 and 100 would put 1 halfway across. The line is not fitted here: it
 * is drawn from the slope and intercept the API computed on every complete
 * row, so a chart showing a 2,000-point sample still carries the fit of all
 * of them, and the caption says so.
 */

interface Props {
  config: ChartConfig;
  height?: number;
}

// Pinned so the caption reads the same on every machine, and so tests do not
// depend on the runner's locale.
const LOCALE = "en-US";
// Bubble areas in px², smallest to largest size value. Area, not radius, so a
// value twice as large reads as twice as big. The ceiling keeps the largest
// bubble at a radius of about 11px, so forty overlapping bubbles in the
// 360px panel still read as points rather than one blob.
const BUBBLE_AREA: [number, number] = [30, 420];
// The missing-label bucket: neutral, so it never competes with a real group
// for one of the twelve hues (it is always last in the legend).
const MISSING_COLOR = "#9CA3AF";
const TICK = { fontSize: 11, fill: "var(--ink-muted, #9ca3af)" };
const AXIS_LINE = { stroke: "var(--line)" };
const LABEL = { fontSize: 11, fill: "var(--ink-muted, #9ca3af)" };

function formatP(pValue: number): string {
  return pValue < 0.001 ? "p < 0.001" : `p = ${formatStatistic(pValue, 3)}`;
}

function equation(view: ScatterView): string | null {
  if (!view.fit) return null;
  const { slope, intercept } = view.fit;
  const sign = intercept < 0 ? "−" : "+";
  return `${view.yField} = ${formatStatistic(slope)} × ${view.xField} ${sign} ${formatStatistic(Math.abs(intercept))}`;
}

function PointTooltip({
  active,
  payload,
  view,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload: ScatterPoint }>;
  view: ScatterView;
}) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] px-2.5 py-1.5 text-[11px] shadow-sm">
      <p className="text-ink">
        {view.xField}: {formatStatistic(point.x)}
      </p>
      <p className="text-ink">
        {view.yField}: {formatStatistic(point.y)}
      </p>
      {point.size !== null && view.sizeField ? (
        <p className="text-ink-muted">
          {view.sizeField}: {formatStatistic(point.size)}
        </p>
      ) : null}
      {point.group !== null && view.groupField ? (
        <p className="text-ink-muted">
          {view.groupField}: {point.group}
        </p>
      ) : null}
    </div>
  );
}

function Legend({ view, colorOf }: { view: ScatterView; colorOf: (index: number) => string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[11px] text-ink-muted">
      {view.groups.map((group, index) => (
        <span key={group} className="flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: colorOf(index) }}
            aria-hidden
          />
          {group}
        </span>
      ))}
      {view.fit ? (
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded" style={{ background: BRAND_GOLD }} aria-hidden />
          OLS fit
        </span>
      ) : null}
    </div>
  );
}

function Caption({ view }: { view: ScatterView }) {
  const parts: string[] = [];
  if (view.n !== null) parts.push(`n = ${view.n.toLocaleString(LOCALE)}`);
  const fitted = equation(view);
  if (view.fit && fitted) {
    if (view.fit.rSquared !== null) parts.push(`R² = ${formatStatistic(view.fit.rSquared)}`);
    parts.push(fitted);
    if (view.fit.pValue !== null) parts.push(`slope ${formatP(view.fit.pValue)}`);
  }
  return (
    <div className="space-y-0.5 px-1 text-[11px] leading-relaxed text-ink-muted">
      {parts.length > 0 ? <p>{parts.join(" · ")}</p> : null}
      {view.sampled && view.totalPoints !== null ? (
        <p>
          Showing a random sample of {view.plotted.toLocaleString(LOCALE)} of{" "}
          {view.totalPoints.toLocaleString(LOCALE)} points; the line is fitted to
          all of them.
        </p>
      ) : null}
      {view.unplottedGroups.length > 0 ? (
        <p>
          No points from {view.unplottedGroups.join(", ")} fall in this sample;
          the legend and the fit still include them.
        </p>
      ) : null}
      {view.sizeField ? (
        <p>
          Bubble area shows {view.sizeField}
          {view.sizeRange
            ? ` (${formatStatistic(view.sizeRange[0])} to ${formatStatistic(view.sizeRange[1])})`
            : ""}
          ; the line ignores it.
        </p>
      ) : null}
    </div>
  );
}

export function ScatterPlot({ config, height = 260 }: Props) {
  const view = useMemo(() => toScatterView(config), [config]);
  if (!view) {
    return (
      <p className="flex h-24 items-center justify-center text-[12px] text-ink-muted">
        No plottable points: this chart has no rows with numeric values on both
        axes.
      </p>
    );
  }

  const series = scatterSeries(view);
  const segment = fitSegment(view);
  const colorOf = (index: number) => {
    if (view.groups.length === 0) return BRAND_PURPLE;
    if (view.groups[index] === MISSING_GROUP) return MISSING_COLOR;
    return GROUP_COLORS[index % GROUP_COLORS.length];
  };

  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 20, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" opacity={0.6} />
          <XAxis
            type="number"
            dataKey="x"
            name={view.xField}
            domain={["auto", "auto"]}
            tick={TICK}
            tickLine={false}
            axisLine={AXIS_LINE}
            label={{ value: view.xField, position: "insideBottom", offset: -12, ...LABEL }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={view.yField}
            domain={["auto", "auto"]}
            width={56}
            tick={TICK}
            tickLine={false}
            axisLine={AXIS_LINE}
            label={{
              value: view.yField,
              angle: -90,
              position: "insideLeft",
              offset: 14,
              style: { textAnchor: "middle" },
              ...LABEL,
            }}
          />
          {view.sizeField ? (
            <ZAxis
              type="number"
              dataKey="size"
              name={view.sizeField}
              range={BUBBLE_AREA}
              domain={view.sizeRange ? [...view.sizeRange] : ["auto", "auto"]}
            />
          ) : null}
          <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<PointTooltip view={view} />} />
          {series.map((entry, index) => (
            <Scatter
              key={entry.name ?? "points"}
              name={entry.name ?? view.yField}
              data={[...entry.points]}
              fill={colorOf(index)}
              fillOpacity={view.sizeField ? 0.45 : 0.7}
              isAnimationActive={false}
            />
          ))}
          {segment ? (
            <ReferenceLine
              segment={[...segment]}
              stroke={BRAND_GOLD}
              strokeWidth={2}
              ifOverflow="extendDomain"
            />
          ) : null}
        </ScatterChart>
      </ResponsiveContainer>
      {view.groups.length > 0 ? <Legend view={view} colorOf={colorOf} /> : null}
      <Caption view={view} />
    </div>
  );
}
