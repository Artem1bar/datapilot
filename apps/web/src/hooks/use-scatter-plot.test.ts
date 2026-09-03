import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useScatterPlot } from "./use-scatter-plot";
import { useSessionStore } from "@/stores/session-store";
import { useAppStore } from "@/stores/app-store";
import { api } from "@/lib/api";
import type { ChartConfig } from "@/types";

vi.mock("@/lib/api", () => ({
  api: { post: vi.fn(), get: vi.fn() },
}));

const chart: ChartConfig = {
  chart_type: "scatter",
  title: "revenue vs units",
  x_field: "units",
  y_field: "revenue",
  data: [
    { x: 1, y: 10 },
    { x: 2, y: 21 },
    { x: 3, y: 29 },
  ],
  options: { computed: true, n: 3, fit: { slope: 9.5, intercept: 1 } },
};

const turn = {
  answer: "Scatter plot of revenue against units over 3 complete rows.",
  charts: [chart],
  tables: [],
  provenance: null,
};

function sessionWithDataset(datasetId: string | null = "ds-1"): string {
  const id = useSessionStore.getState().createSession("Plots");
  if (datasetId) useSessionStore.getState().setSessionDatasetId(id, datasetId);
  return id;
}

beforeEach(() => {
  useSessionStore.setState({
    sessions: [],
    activeSessionId: null,
    messagesBySession: {},
    workflowStateBySession: {},
    activeCleaningJobsBySession: {},
  });
  useAppStore.setState({ charts: [], chartPanelOpen: false });
  vi.mocked(api.post).mockReset();
});

describe("useScatterPlot", () => {
  it("posts the request and records the plot in the conversation and the panel", async () => {
    const sessionId = sessionWithDataset();
    vi.mocked(api.post).mockReturnValue({
      json: () => Promise.resolve(turn),
    } as never);

    const { result } = renderHook(() => useScatterPlot());
    let outcome: Awaited<ReturnType<typeof result.current.plot>> | undefined;
    await act(async () => {
      outcome = await result.current.plot({
        x: "units",
        y: "revenue",
        colorBy: null,
        size: "orders",
      });
    });

    expect(outcome).toEqual({ ok: true });
    expect(api.post).toHaveBeenCalledWith(
      "analysis/ds-1/scatter",
      expect.objectContaining({
        json: { x: "units", y: "revenue", color_by: null, size: "orders" },
      }),
    );

    const messages = useSessionStore.getState().messagesBySession[sessionId];
    expect(messages.map((m) => [m.role, m.card?.type ?? m.content])).toEqual([
      ["user", "Scatter plot of revenue against units, sized by orders"],
      ["assistant", turn.answer],
      ["assistant", "visualization"],
    ]);
    expect(useAppStore.getState().charts).toEqual([chart]);
    expect(useAppStore.getState().chartPanelOpen).toBe(true);
    expect(result.current.plotting).toBe(false);
  });

  it("refuses without a dataset and does not call the API", async () => {
    sessionWithDataset(null);
    const { result } = renderHook(() => useScatterPlot());

    let outcome: Awaited<ReturnType<typeof result.current.plot>> | undefined;
    await act(async () => {
      outcome = await result.current.plot({ x: "a", y: "b", colorBy: null, size: null });
    });

    expect(outcome?.ok).toBe(false);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("reports a failure in the conversation and to the caller", async () => {
    const sessionId = sessionWithDataset();
    vi.mocked(api.post).mockReturnValue({
      json: () => Promise.reject(new Error("column 'a' is not numeric")),
    } as never);

    const { result } = renderHook(() => useScatterPlot());
    let outcome: Awaited<ReturnType<typeof result.current.plot>> | undefined;
    await act(async () => {
      outcome = await result.current.plot({ x: "a", y: "b", colorBy: null, size: null });
    });

    expect(outcome).toEqual({ ok: false, error: "column 'a' is not numeric" });
    const messages = useSessionStore.getState().messagesBySession[sessionId];
    const last = messages[messages.length - 1];
    expect(last.role).toBe("system");
    expect(last.content).toContain("is not numeric");
    expect(useAppStore.getState().charts).toEqual([]);
  });
});

describe("useScatterPlot — methods note", () => {
  it("records the methods card when the provenance arrives", async () => {
    const sessionId = sessionWithDataset();
    vi.mocked(api.post).mockReturnValue({
      json: () =>
        Promise.resolve({
          ...turn,
          provenance: {
            question: "Scatter plot of revenue against units",
            dataset: { filename: "sales.csv", rows: 3, columns: 2 },
            operations: [
              {
                index: 0,
                spec_index: 0,
                op: "scatter_with_fit",
                label: "revenue vs units",
                params: { x: "units", y: "revenue" },
                n: 3,
                n_excluded: 0,
                notes: [],
                statistics: { slope: 9.5 },
              },
            ],
            environment: { python: "3.12" },
            methods_note: "Computed by pandas and scipy; no figure came from a language model.",
            code: null,
          },
        }),
    } as never);

    const { result } = renderHook(() => useScatterPlot());
    await act(async () => {
      await result.current.plot({ x: "units", y: "revenue", colorBy: null, size: null });
    });

    const messages = useSessionStore.getState().messagesBySession[sessionId];
    expect(messages.map((m) => m.card?.type ?? m.role)).toEqual([
      "user",
      "assistant",
      "visualization",
      "analysis_methods",
    ]);
  });
});
