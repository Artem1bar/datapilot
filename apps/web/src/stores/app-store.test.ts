import { describe, it, expect, beforeEach } from "vitest";
import { useAppStore } from "./app-store";

// Reset store before each test to avoid state bleed
beforeEach(() => {
  useAppStore.setState({
    sidebarOpen: true,
    chartPanelOpen: false,
    charts: [],
    theme: "system",
  });
});

describe("AppStore — sidebar", () => {
  it("toggles sidebarOpen from true to false", () => {
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarOpen).toBe(false);
  });

  it("toggles sidebarOpen from false to true", () => {
    useAppStore.setState({ sidebarOpen: false });
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarOpen).toBe(true);
  });

  it("setSidebarOpen sets an explicit value", () => {
    useAppStore.getState().setSidebarOpen(false);
    expect(useAppStore.getState().sidebarOpen).toBe(false);
    useAppStore.getState().setSidebarOpen(true);
    expect(useAppStore.getState().sidebarOpen).toBe(true);
  });
});

describe("AppStore — chart panel", () => {
  it("toggles chartPanelOpen", () => {
    useAppStore.getState().toggleChartPanel();
    expect(useAppStore.getState().chartPanelOpen).toBe(true);
    useAppStore.getState().toggleChartPanel();
    expect(useAppStore.getState().chartPanelOpen).toBe(false);
  });

  it("setChartPanelOpen sets an explicit value", () => {
    useAppStore.getState().setChartPanelOpen(true);
    expect(useAppStore.getState().chartPanelOpen).toBe(true);
  });
});

describe("AppStore — charts", () => {
  const chart = {
    chart_type: "bar",
    title: "Revenue",
    x_field: "month",
    y_field: "amount",
    data: [],
    options: {},
  };

  it("addCharts appends charts to the list", () => {
    useAppStore.getState().addCharts([chart]);
    expect(useAppStore.getState().charts).toHaveLength(1);
    expect(useAppStore.getState().charts[0]).toEqual(chart);
  });

  it("addCharts accumulates across calls", () => {
    useAppStore.getState().addCharts([chart]);
    useAppStore.getState().addCharts([chart]);
    expect(useAppStore.getState().charts).toHaveLength(2);
  });

  it("clearCharts empties the list", () => {
    useAppStore.getState().addCharts([chart]);
    useAppStore.getState().clearCharts();
    expect(useAppStore.getState().charts).toHaveLength(0);
  });
});

describe("AppStore — theme", () => {
  it("setTheme updates the theme", () => {
    useAppStore.getState().setTheme("dark");
    expect(useAppStore.getState().theme).toBe("dark");
  });

  it("setTheme accepts all valid values", () => {
    for (const theme of ["light", "dark", "system"] as const) {
      useAppStore.getState().setTheme(theme);
      expect(useAppStore.getState().theme).toBe(theme);
    }
  });
});
