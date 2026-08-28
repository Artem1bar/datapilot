import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TriangleAlert } from "lucide-react";
import { formatLevel, formatStatistic } from "@/lib/analysis-format";
import type { AnalysisForecastPoint, AnalysisForecastView } from "@/types";

/**
 * Observed history and a forecast, with the forecast's prediction interval.
 *
 * The interval is not an option here. A forecast line drawn on its own reads as
 * a measurement of the future, and the whole content of a forecast is how wide
 * the range of futures is — an ARIMA point forecast eight periods out can carry
 * an interval several times the size of the series' own variation, and a reader
 * shown only the line has been told the opposite of what the model found. So
 * the band is drawn first and always, and a forecast that somehow arrives
 * without one is labelled as unusable rather than quietly drawn as a line.
 *
 * Observed and forecast are separate series with different strokes, so the
 * boundary between what was measured and what was extrapolated is visible
 * without reading the axis.
 */

interface Props {
  view: AnalysisForecastView;
}

const OBSERVED = "#461D7C"; // LSU purple, matching ChartRenderer's palette
const FORECAST = "#D97706"; // warm orange — distinct at a glance, not a hue shift

/** Trim a pandas ISO timestamp to the part a reader needs. */
function shortDate(value: string): string {
  return value.split("T")[0];
}

/** The API's phrases are sentence fragments; this one ends up starting one. */
function asSentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function IntervalTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload: AnalysisForecastPoint }>;
  label?: string | number;
}) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] px-2.5 py-1.5 text-[11px] shadow-sm">
      <p className="font-medium text-ink">
        {shortDate(String(label ?? point.date))}
      </p>
      {point.observed !== null ? (
        <p className="text-ink-muted">
          Observed {formatStatistic(point.observed)}
        </p>
      ) : null}
      {point.forecast !== null && point.observed === null ? (
        <p className="text-ink-muted">
          Forecast {formatStatistic(point.forecast)}
        </p>
      ) : null}
      {point.interval && point.observed === null ? (
        <p className="text-ink-muted">
          Interval [{formatStatistic(point.interval[0])},{" "}
          {formatStatistic(point.interval[1])}]
        </p>
      ) : null}
    </div>
  );
}

function Legend({ level }: { level: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 pb-2 text-[11px] text-ink-muted">
      <span className="flex items-center gap-1.5">
        <span
          className="h-0.5 w-4 rounded"
          style={{ background: OBSERVED }}
          aria-hidden
        />
        Observed
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="h-0.5 w-4 rounded"
          style={{
            backgroundImage: `repeating-linear-gradient(90deg, ${FORECAST} 0 4px, transparent 4px 7px)`,
          }}
          aria-hidden
        />
        Forecast
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="h-2.5 w-4 rounded-sm"
          style={{ background: FORECAST, opacity: 0.18 }}
          aria-hidden
        />
        {level} prediction interval
      </span>
    </div>
  );
}

export function AnalysisForecastChart({ view }: Props) {
  const level = formatLevel(view.level);

  if (!view.hasInterval) {
    // Refusing to draw is the honest response. A point forecast with no
    // interval is not a weaker version of a forecast; it is a claim about the
    // future with its uncertainty deleted.
    return (
      <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <span>
          This forecast arrived without a prediction interval, so it is not
          drawn. A forecast line on its own reads as a measurement of the
          future; the interval is the finding.
        </span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)]">
      {view.model ? (
        <p className="border-b border-[var(--line)] px-3 py-2 text-[12px] font-medium text-ink">
          {view.model}
        </p>
      ) : null}

      <div className="px-1 pt-3">
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart
            data={[...view.points]}
            margin={{ top: 4, right: 12, bottom: 4, left: 4 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--line)"
              opacity={0.6}
            />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={{ fontSize: 10 }}
              stroke="var(--line)"
              minTickGap={24}
            />
            {/* Fitted to the data rather than anchored at zero. A line chart of
                a series that oscillates around 50 is not misleading for
                omitting the origin, and a zero baseline squashes the
                prediction interval into a hairline — which would hide the one
                thing this chart exists to show. */}
            <YAxis
              tick={{ fontSize: 10 }}
              stroke="var(--line)"
              width={48}
              domain={["auto", "auto"]}
            />
            <Tooltip content={<IntervalTooltip />} />
            {/* The band is drawn before the lines so it sits behind them. */}
            <Area
              dataKey="interval"
              name={`${level} prediction interval`}
              stroke="none"
              fill={FORECAST}
              fillOpacity={0.18}
              isAnimationActive={false}
            />
            <Line
              dataKey="observed"
              name="Observed"
              type="monotone"
              stroke={OBSERVED}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="forecast"
              name="Forecast"
              type="monotone"
              stroke={FORECAST}
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <Legend level={level} />

      <p className="border-t border-[var(--line)] px-3 py-2 text-[11px] leading-relaxed text-ink-muted">
        {view.periods} period{view.periods === 1 ? "" : "s"} ahead.{" "}
        {view.intervalMeaning
          ? `${asSentence(view.intervalMeaning)}.`
          : "The shaded band is a prediction interval for a future observation, not a confidence interval for an average."}
      </p>
    </div>
  );
}
