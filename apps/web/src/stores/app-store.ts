import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChartConfig } from "@/types";

type Theme = "light" | "dark" | "system";

interface AppState {
  sidebarOpen: boolean;
  chartPanelOpen: boolean;
  charts: ChartConfig[];
  // One dialog, opened from the attach menu or the chart panel; the launcher
  // that renders it lives in the layout.
  scatterDialogOpen: boolean;
  theme: Theme;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleChartPanel: () => void;
  setChartPanelOpen: (open: boolean) => void;
  addCharts: (charts: ChartConfig[]) => void;
  clearCharts: () => void;
  openScatterDialog: () => void;
  closeScatterDialog: () => void;
  setTheme: (theme: Theme) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      chartPanelOpen: false,
      charts: [],
      scatterDialogOpen: false,
      theme: "system",

      toggleSidebar: () =>
        set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      toggleChartPanel: () =>
        set((state) => ({ chartPanelOpen: !state.chartPanelOpen })),
      setChartPanelOpen: (open) => set({ chartPanelOpen: open }),

      addCharts: (charts) =>
        set((state) => ({ charts: [...state.charts, ...charts] })),
      clearCharts: () => set({ charts: [] }),

      openScatterDialog: () => set({ scatterDialogOpen: true }),
      closeScatterDialog: () => set({ scatterDialogOpen: false }),

      setTheme: (theme) => set({ theme }),
    }),
    {
      // Pre-rename localStorage key — changing it would drop users' local settings.
      name: "datatiger-app",
      // Don't persist charts or dialog state — they're session-specific
      partialize: (state) => ({
        sidebarOpen: state.sidebarOpen,
        theme: state.theme,
      }),
    },
  ),
);
