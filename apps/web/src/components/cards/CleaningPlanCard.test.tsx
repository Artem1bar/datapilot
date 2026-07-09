import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CleaningPlanCard } from "./CleaningPlanCard";
import type { CleaningPlanPayload } from "@/types";

function makePayload(): CleaningPlanPayload {
  return {
    type: "cleaning_plan",
    summary: "Test plan",
    datasetId: "ds-1",
    steps: [
      {
        operation: "strip_whitespace",
        column: "name",
        params: {},
        description: "Step 1: strip",
        confidence: 0.9,
        rationale: "spaces",
      },
      {
        operation: "drop_rows",
        column: null,
        params: { indices: [0] },
        description: "Step 2: drop header",
        confidence: 0.8,
      },
    ],
  };
}

// Both toggle buttons carry an aria-label containing "this step"; the Apply
// button does not — so this reliably selects only the per-step toggles.
const toggles = () => screen.getAllByRole("button", { name: /this step/i });

describe("CleaningPlanCard", () => {
  it("renders every step and an Apply button reflecting the full count", () => {
    render(<CleaningPlanCard payload={makePayload()} />);

    expect(screen.getByText("Step 1: strip")).toBeInTheDocument();
    expect(screen.getByText("Step 2: drop header")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Apply 2 steps$/ })).toBeEnabled();
    expect(toggles()).toHaveLength(2);
  });

  it("toggling a step off updates the selected count and Apply label", async () => {
    const user = userEvent.setup();
    render(<CleaningPlanCard payload={makePayload()} />);

    await user.click(toggles()[1]);

    expect(screen.getByRole("button", { name: /^Apply 1 step$/ })).toBeEnabled();
    expect(screen.getByText("1 of 2 selected")).toBeInTheDocument();
  });

  it("clicking Apply dispatches apply_cleaning with the datasetId and stripped steps", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<CleaningPlanCard payload={makePayload()} onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: /^Apply 2 steps$/ }));

    expect(onAction).toHaveBeenCalledTimes(1);
    const [action, data] = onAction.mock.calls[0] as [string, { datasetId: string; steps: unknown[] }];
    expect(action).toBe("apply_cleaning");
    expect(data.datasetId).toBe("ds-1");
    expect(data.steps).toHaveLength(2);
    // UI-only fields must be stripped before hitting the API.
    expect(data.steps[0]).not.toHaveProperty("confidence");
    expect(data.steps[0]).not.toHaveProperty("rationale");
    expect(data.steps[0]).toMatchObject({
      operation: "strip_whitespace",
      column: "name",
      description: "Step 1: strip",
    });
  });

  it("excludes toggled-off steps from the dispatched payload", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<CleaningPlanCard payload={makePayload()} onAction={onAction} />);

    await user.click(toggles()[1]); // turn off step 2
    await user.click(screen.getByRole("button", { name: /^Apply 1 step$/ }));

    const data = onAction.mock.calls[0][1] as { steps: Array<{ description: string }> };
    expect(data.steps).toHaveLength(1);
    expect(data.steps[0].description).toBe("Step 1: strip");
  });

  it("disables Apply and shows Applied after applying, preventing a second dispatch", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<CleaningPlanCard payload={makePayload()} onAction={onAction} />);

    const applyBtn = screen.getByRole("button", { name: /^Apply 2 steps$/ });
    await user.click(applyBtn);

    const appliedBtn = screen.getByRole("button", { name: /Applied/ });
    expect(appliedBtn).toBeDisabled();
    await user.click(appliedBtn);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("disables Apply when no steps are selected", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<CleaningPlanCard payload={makePayload()} onAction={onAction} />);

    await user.click(toggles()[0]);
    await user.click(toggles()[1]);

    expect(screen.getByRole("button", { name: /^Apply 0 steps$/ })).toBeDisabled();
  });

  it("renders as already Applied when the payload is marked applied (survives remount)", () => {
    render(<CleaningPlanCard payload={{ ...makePayload(), applied: true }} />);
    expect(screen.getByRole("button", { name: /Applied/ })).toBeDisabled();
  });

  it("includes the messageId in the apply payload so the store can persist applied state", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<CleaningPlanCard payload={makePayload()} messageId="msg-42" onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: /^Apply 2 steps$/ }));

    const data = onAction.mock.calls[0][1] as { messageId?: string };
    expect(data.messageId).toBe("msg-42");
  });
});
