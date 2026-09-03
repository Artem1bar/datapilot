import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChartPanel } from "./ChartPanel";
import { useAppStore } from "@/stores/app-store";
import { useSessionStore } from "@/stores/session-store";

beforeEach(() => {
  useAppStore.setState({ chartPanelOpen: true, charts: [], scatterDialogOpen: false });
  useSessionStore.setState({
    sessions: [],
    activeSessionId: null,
    messagesBySession: {},
    workflowStateBySession: {},
    activeCleaningJobsBySession: {},
  });
});

describe("ChartPanel — plotting on demand", () => {
  it("offers a scatter plot from the empty state once a dataset is attached", async () => {
    const user = userEvent.setup();
    const id = useSessionStore.getState().createSession("s");
    useSessionStore.getState().setSessionDatasetId(id, "ds-1");

    render(<ChartPanel />);
    await user.click(screen.getByRole("button", { name: /plot a scatter/i }));
    expect(useAppStore.getState().scatterDialogOpen).toBe(true);
  });

  it("explains that a dataset is needed first", () => {
    render(<ChartPanel />);
    expect(screen.getByRole("button", { name: /plot a scatter/i })).toBeDisabled();
    expect(screen.getByText(/attach a dataset/i)).toBeInTheDocument();
  });
});
