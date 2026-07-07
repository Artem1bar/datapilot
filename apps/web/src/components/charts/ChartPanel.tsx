import { lazy, Suspense } from "react";
import { X, BarChart3, TrendingUp, Trash2 } from "lucide-react";
import { motion } from "framer-motion";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";

// recharts is heavy (~800 kB unminified); load ChartRenderer only when a chart
// actually renders so recharts stays out of the initial bundle.
const ChartRenderer = lazy(() =>
  import("@/components/shared/ChartRenderer").then((m) => ({
    default: m.ChartRenderer,
  })),
);

export function ChartPanel() {
  const chartPanelOpen = useAppStore((s) => s.chartPanelOpen);
  const charts = useAppStore((s) => s.charts);
  const setChartPanelOpen = useAppStore((s) => s.setChartPanelOpen);
  const clearCharts = useAppStore((s) => s.clearCharts);

  return (
    <motion.div
      animate={{ width: chartPanelOpen ? 360 : 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="flex h-full flex-col border-l border-[var(--line)] bg-[var(--surface-primary)] overflow-hidden"
    >
      {/* Always render the interior so transitions work smoothly */}
      <div className="flex h-full w-[360px] flex-col">
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div
          className="flex h-14 shrink-0 items-center justify-between px-4"
          style={{ background: "var(--brand-600, #461D7C)" }}
        >
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-white/80" />
            <span className="text-sm font-semibold text-white">
              Visualizations
              {charts.length > 0 && (
                <span className="ml-1.5 rounded-full bg-white/20 px-1.5 py-0.5 text-[11px] font-medium text-white">
                  {charts.length}
                </span>
              )}
            </span>
          </div>

          <div className="flex items-center gap-1">
            {charts.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                onClick={clearCharts}
                className="h-7 w-7 text-white/60 hover:bg-white/10 hover:text-white"
                title="Clear all charts"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setChartPanelOpen(false)}
              className="h-7 w-7 text-white/70 hover:bg-white/10 hover:text-white"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* ── Body ───────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-4">
          {charts.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50">
                <TrendingUp className="h-7 w-7 text-brand-300" />
              </div>
              <p className="text-[13px] leading-relaxed text-ink-muted">
                Analyze your data and charts will appear here automatically.
              </p>
            </div>
          ) : (
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center py-10 text-[13px] text-ink-muted">
                  Loading charts…
                </div>
              }
            >
              <div className="space-y-5">
                {charts.map((chart, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-[var(--line)] bg-[var(--surface-canvas)] p-4 shadow-sm"
                  >
                    <ChartRenderer config={chart} data={chart.data} />
                  </div>
                ))}
              </div>
            </Suspense>
          )}
        </div>
      </div>
    </motion.div>
  );
}
