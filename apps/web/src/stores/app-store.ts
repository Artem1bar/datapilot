import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChartConfig } from "@/types";

type Theme = "light" | "dark" | "system";

interface AppState {
  sidebarOpen: boolean;
  chartPanelOpen: boolean;
  charts: ChartConfig[];
  theme: Theme;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleChartPanel: () => void;
  setChartPanelOpen: (open: boolean) => void;
  addCharts: (charts: ChartConfig[]) => void;
  clearCharts: () => void;
  setTheme: (theme: Theme) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      chartPanelOpen: false,
      charts: [],
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

      setTheme: (theme) => set({ theme }),
    }),
    {
      // Pre-rename localStorage key — changing it would drop users' local settings.
      name: "datatiger-app",
      // Don't persist charts — they're session-specific
      partialize: (state) => ({
        sidebarOpen: state.sidebarOpen,
        theme: state.theme,
      }),
    },
  ),
);
