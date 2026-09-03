import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ScatterPlotLauncher } from "./ScatterPlotLauncher";
import { useAppStore } from "@/stores/app-store";
import { useSessionStore } from "@/stores/session-store";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { post: vi.fn(), get: vi.fn() },
}));

const dataset = {
  id: "ds-1",
  filename: "sales.csv",
  profile_json: {
    columns: {
      units: { dtype: "int64", unique_count: 40 },
      revenue: { dtype: "float64", unique_count: 50 },
      region: { dtype: "object", unique_count: 3 },
    },
  },
};

const turn = {
  answer: "Scatter plot of revenue against units over 3 complete rows.",
  charts: [
    {
      chart_type: "scatter",
      title: "revenue vs units",
      x_field: "units",
      y_field: "revenue",
      data: [{ x: 1, y: 2 }],
      options: {},
    },
  ],
  tables: [],
  provenance: null,
};

beforeEach(() => {
  useSessionStore.setState({
    sessions: [],
    activeSessionId: null,
    messagesBySession: {},
    workflowStateBySession: {},
    activeCleaningJobsBySession: {},
  });
  useAppStore.setState({ charts: [], chartPanelOpen: false, scatterDialogOpen: false });
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

describe("ScatterPlotLauncher", () => {
  it("loads the dataset's columns, plots, and closes", async () => {
    const user = userEvent.setup();
    const id = useSessionStore.getState().createSession("s");
    useSessionStore.getState().setSessionDatasetId(id, "ds-1");
    vi.mocked(api.get).mockReturnValue({
      json: () => Promise.resolve(dataset),
    } as never);
    vi.mocked(api.post).mockReturnValue({
      json: () => Promise.resolve(turn),
    } as never);

    render(<ScatterPlotLauncher />);
    useAppStore.getState().openScatterDialog();

    // Choices are listed by name, so "revenue" precedes "units".
    expect(await screen.findByLabelText("X axis")).toHaveValue("revenue");
    expect(api.get).toHaveBeenCalledWith("datasets/ds-1");

    await user.click(screen.getByRole("button", { name: "Plot" }));

    await waitFor(() =>
      expect(useAppStore.getState().scatterDialogOpen).toBe(false),
    );
    expect(api.post).toHaveBeenCalledWith(
      "analysis/ds-1/scatter",
      expect.objectContaining({
        json: { x: "revenue", y: "units", color_by: null, size: null },
      }),
    );
    expect(useAppStore.getState().charts).toHaveLength(1);
  });

  it("stays open and shows the problem when the plot is refused", async () => {
    const user = userEvent.setup();
    const id = useSessionStore.getState().createSession("s");
    useSessionStore.getState().setSessionDatasetId(id, "ds-1");
    vi.mocked(api.get).mockReturnValue({
      json: () => Promise.resolve(dataset),
    } as never);
    vi.mocked(api.post).mockReturnValue({
      json: () => Promise.reject(new Error("only 2 complete row(s); need at least 3")),
    } as never);

    render(<ScatterPlotLauncher />);
    useAppStore.getState().openScatterDialog();
    await screen.findByLabelText("X axis");

    await user.click(screen.getByRole("button", { name: "Plot" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("at least 3");
    expect(useAppStore.getState().scatterDialogOpen).toBe(true);
  });

  it("explains when no dataset is attached", async () => {
    useSessionStore.getState().createSession("s");
    render(<ScatterPlotLauncher />);
    useAppStore.getState().openScatterDialog();

    expect(await screen.findByRole("alert")).toHaveTextContent(/attach a dataset/i);
    expect(api.get).not.toHaveBeenCalled();
  });
});
