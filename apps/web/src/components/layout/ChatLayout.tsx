import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useAppStore } from "@/stores/app-store";
import { SessionSidebar } from "./SessionSidebar";
import { ApiStatusBanner } from "./ApiStatusBanner";
import { ChartPanel } from "@/components/charts/ChartPanel";
import { ScatterPlotLauncher } from "@/components/charts/ScatterPlotLauncher";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Toaster } from "@/components/ui/toaster";
import { BarChart3 } from "lucide-react";

export function ChatLayout() {
  const isMobile = useMediaQuery("(max-width: 768px)");
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);
  const chartPanelOpen = useAppStore((s) => s.chartPanelOpen);
  const toggleChartPanel = useAppStore((s) => s.toggleChartPanel);
  const charts = useAppStore((s) => s.charts);
  const theme = useAppStore((s) => s.theme);

  // Keep dark class in sync with store
  useEffect(() => {
    const isDark =
      theme === "dark" ||
      (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", isDark);
  }, [theme]);

  if (isMobile) {
    return (
      <div className="flex h-screen flex-col bg-[var(--surface-canvas)]">
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetContent side="left" className="w-[260px] p-0">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SessionSidebar />
          </SheetContent>
        </Sheet>
        <ApiStatusBanner />
        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
        <ScatterPlotLauncher />
        <Toaster />
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[var(--surface-canvas)]">
      <SessionSidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <ApiStatusBanner />

        {/* Main content + right panel wrapper */}
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          {/* Chat area */}
          <main className="flex flex-1 flex-col overflow-hidden">
            <Outlet />
          </main>

          {/* Chart panel toggle tab — only when panel is closed */}
          {!chartPanelOpen && (
            <button
              type="button"
              onClick={toggleChartPanel}
              title="Open visualizations panel"
              className="absolute right-0 top-1/2 z-20 flex -translate-y-1/2 flex-col items-center gap-1.5 rounded-l-xl border border-r-0 border-[var(--line)] bg-[var(--surface-primary)] px-2 py-3 shadow-sm transition-all duration-150 hover:bg-brand-50 hover:border-brand-200 active:scale-95"
            >
              <BarChart3 className="h-4 w-4 text-brand-500" />
              {charts.length > 0 && (
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-brand-600 text-[10px] font-bold text-white">
                  {charts.length > 9 ? "9+" : charts.length}
                </span>
              )}
              <span
                className="text-[10px] font-medium text-ink-muted"
                style={{ writingMode: "vertical-rl", textOrientation: "mixed", transform: "rotate(180deg)" }}
              >
                Charts
              </span>
            </button>
          )}

          {/* Chart panel */}
          <ChartPanel />
        </div>
      </div>

      <ScatterPlotLauncher />
      <Toaster />
    </div>
  );
}
