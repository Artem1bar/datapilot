import { lazy, Suspense } from "react";
import { PlotReading } from "@/components/charts/PlotReading";
import { toScatterView } from "@/lib/scatter";
import type { VisualizationPayload } from "@/types";

// recharts is heavy; load the renderer only when a chart is actually in the
// conversation, the same treatment ChartPanel gives it.
const ChartRenderer = lazy(() =>
  import("@/components/shared/ChartRenderer").then((m) => ({
    default: m.ChartRenderer,
  })),
);

interface Props {
  payload: VisualizationPayload;
  /** "ask" puts a follow-up question into the chat input. */
  onAction?: (action: string, data?: unknown) => void;
}

const READABLE_TYPES = new Set(["scatter", "bubble"]);

/** A chart in the conversation itself, so a plot survives the panel being cleared. */
export function VisualizationCard({ payload, onAction }: Props) {
  const reading = READABLE_TYPES.has(payload.chart.chart_type)
    ? toScatterView(payload.chart)?.interpretation ?? null
    : null;

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] p-4 shadow-sm">
        <Suspense
          fallback={<p className="py-6 text-center text-[13px] text-ink-muted">Loading chart…</p>}
        >
          <ChartRenderer config={payload.chart} data={payload.chart.data} />
        </Suspense>
        {payload.description ? (
          <p className="mt-2 text-[12px] leading-relaxed text-ink-muted">{payload.description}</p>
        ) : null}
        {reading ? (
          <PlotReading reading={reading} onAsk={(question) => onAction?.("ask", question)} />
        ) : null}
      </div>
    </div>
  );
}
