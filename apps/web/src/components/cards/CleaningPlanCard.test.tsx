import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CleaningPlanCard } from "./CleaningPlanCard";
import type { CleaningPlanPayload } from "@/types";
import type { OperationCatalog } from "@/lib/plan-editor";

/* ── The catalogue and the validate call are the card's two API deps ─────── */

const CATALOG: OperationCatalog = {
  groups: ["Structural", "Standardization", "Anomalies"],
  operations: [
    {
      name: "strip_whitespace",
      label: "Strip whitespace",
      group: "Standardization",
      summary: "Remove leading and trailing spaces.",
      requiresColumn: true,
      destructive: false,
      requiresOneOf: [],
      params: [],
    },
    {
      name: "drop_rows",
      label: "Drop specific rows",
      group: "Structural",
      summary: "Remove rows by position.",
      requiresColumn: false,
      destructive: true,
      requiresOneOf: [],
      params: [
        {
          name: "indices",
          kind: "integer_list",
          label: "Row indices",
          help: "Zero-based.",
          required: true,
          default: [],
          choices: [],
        },
      ],
    },
    {
      name: "cap_extreme_values",
      label: "Cap extreme values",
      group: "Anomalies",
      summary: "Clear values above a ceiling.",
      requiresColumn: true,
      destructive: true,
      requiresOneOf: [],
      params: [
        {
          name: "max_value",
          kind: "number",
          label: "Ceiling",
          help: "",
          required: true,
          default: null,
          choices: [],
        },
      ],
    },
  ],
};

const getOperationCatalog = vi.fn();
const validatePlan = vi.fn();

vi.mock("@/lib/cleaning-api", () => ({
  getOperationCatalog: () => getOperationCatalog(),
  validatePlan: (...args: unknown[]) => validatePlan(...args),
}));

beforeEach(() => {
  getOperationCatalog.mockResolvedValue(CATALOG);
  validatePlan.mockResolvedValue({ valid: true, issues: [] });
});

afterEach(() => {
  vi.clearAllMocks();
});

function makePayload(overrides: Partial<CleaningPlanPayload> = {}): CleaningPlanPayload {
  return {
    type: "cleaning_plan",
    summary: "Test plan",
    datasetId: "ds-1",
    columns: ["name", "amount"],
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
    ...overrides,
  };
}

// Both toggle buttons carry an aria-label containing "this step"; no other
// control does — so this reliably selects only the per-step toggles.
const toggles = () => screen.getAllByRole("button", { name: /this step/i });
const applyButton = () => screen.getByRole("button", { name: /^Apply|^Applied|^Checking/ });

/** The card loads its catalogue on mount; wait for the editor to be usable. */
async function renderCard(props: Parameters<typeof CleaningPlanCard>[0]) {
  const result = render(<CleaningPlanCard {...props} />);
  await waitFor(() => expect(screen.getByRole("button", { name: /Add a step/ })).toBeEnabled());
  return result;
}

/* ── Reviewing, unchanged from before the editor existed ────────────────── */

describe("CleaningPlanCard — reviewing", () => {
  it("renders every step and an Apply button reflecting the full count", async () => {
    await renderCard({ payload: makePayload() });

    expect(screen.getByText("Step 1: strip")).toBeInTheDocument();
    expect(screen.getByText("Step 2: drop header")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Apply 2 steps$/ })).toBeEnabled();
    expect(toggles()).toHaveLength(2);
  });

  it("says plainly that nothing runs until the plan is approved", async () => {
    await renderCard({ payload: makePayload() });
    expect(screen.getByText(/nothing runs until you approve it/i)).toBeInTheDocument();
  });

  it("toggling a step off updates the selected count and Apply label", async () => {
    const user = userEvent.setup();
    await renderCard({ payload: makePayload() });

    await user.click(toggles()[1]);

    expect(screen.getByRole("button", { name: /^Apply 1 step$/ })).toBeEnabled();
    expect(screen.getByText(/1 of 2 selected/)).toBeInTheDocument();
  });

  it("dispatches apply_cleaning with the datasetId and stripped steps", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(screen.getByRole("button", { name: /^Apply 2 steps$/ }));

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
    const [action, data] = onAction.mock.calls[0] as [
      string,
      { datasetId: string; steps: unknown[]; edited: boolean },
    ];
    expect(action).toBe("apply_cleaning");
    expect(data.datasetId).toBe("ds-1");
    expect(data.steps).toHaveLength(2);
    expect(data.edited).toBe(false);
    // UI-only fields must be stripped before hitting the API.
    expect(data.steps[0]).not.toHaveProperty("confidence");
    expect(data.steps[0]).not.toHaveProperty("rationale");
    expect(data.steps[0]).not.toHaveProperty("uid");
    expect(data.steps[0]).toMatchObject({
      operation: "strip_whitespace",
      column: "name",
      description: "Step 1: strip",
    });
  });

  it("excludes toggled-off steps from the dispatched payload", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(toggles()[1]);
    await user.click(screen.getByRole("button", { name: /^Apply 1 step$/ }));

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
    const data = onAction.mock.calls[0][1] as { steps: Array<{ description: string }> };
    expect(data.steps).toHaveLength(1);
    expect(data.steps[0].description).toBe("Step 1: strip");
  });

  it("disables Apply and shows Applied after applying, preventing a second dispatch", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(screen.getByRole("button", { name: /^Apply 2 steps$/ }));

    const appliedBtn = await screen.findByRole("button", { name: /Applied/ });
    expect(appliedBtn).toBeDisabled();
    await user.click(appliedBtn);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("disables Apply when no steps are selected", async () => {
    const user = userEvent.setup();
    await renderCard({ payload: makePayload() });

    await user.click(toggles()[0]);
    await user.click(toggles()[1]);

    expect(screen.getByRole("button", { name: /^Apply 0 steps$/ })).toBeDisabled();
  });

  it("renders as already Applied when the payload is marked applied (survives remount)", async () => {
    render(<CleaningPlanCard payload={makePayload({ applied: true })} />);
    expect(await screen.findByRole("button", { name: /Applied/ })).toBeDisabled();
  });

  it("hides every editing control once applied", () => {
    render(<CleaningPlanCard payload={makePayload({ applied: true })} />);
    expect(screen.queryByRole("button", { name: /Add a step/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete step/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Move step/ })).not.toBeInTheDocument();
  });

  it("includes the messageId in the apply payload so the store can persist applied state", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), messageId: "msg-42", onAction });

    await user.click(screen.getByRole("button", { name: /^Apply 2 steps$/ }));

    await waitFor(() => expect(onAction).toHaveBeenCalled());
    const data = onAction.mock.calls[0][1] as { messageId?: string };
    expect(data.messageId).toBe("msg-42");
  });
});

/* ── Editing ────────────────────────────────────────────────────────────── */

describe("CleaningPlanCard — editing", () => {
  it("retargets a step at a different column and sends the new one", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(screen.getByRole("button", { name: /Edit step 1 settings/ }));
    await user.selectOptions(screen.getByLabelText(/Target column/), "amount");
    await user.click(applyButton());

    await waitFor(() => expect(onAction).toHaveBeenCalled());
    const data = onAction.mock.calls[0][1] as {
      steps: Array<{ column: string | null }>;
      edited: boolean;
    };
    expect(data.steps[0].column).toBe("amount");
    expect(data.edited).toBe(true);
  });

  it("offers only real dataset columns, so a column cannot be mistyped", async () => {
    const user = userEvent.setup();
    await renderCard({ payload: makePayload() });

    await user.click(screen.getByRole("button", { name: /Edit step 1 settings/ }));
    const select = screen.getByLabelText(/Target column/);
    const options = within(select)
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);
    expect(options).toEqual(["", "name", "amount"]);
  });

  it("edits a numeric param and sends the typed number, not a string", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({
      payload: makePayload({
        steps: [
          {
            operation: "cap_extreme_values",
            column: "amount",
            params: { max_value: 5000 },
            description: "Step 1: cap",
          },
        ],
      }),
      onAction,
    });

    await user.click(screen.getByRole("button", { name: /Edit step 1 settings/ }));
    const ceiling = screen.getByRole("spinbutton");
    await user.clear(ceiling);
    await user.type(ceiling, "250");
    await user.tab(); // commits on blur

    await user.click(applyButton());
    await waitFor(() => expect(onAction).toHaveBeenCalled());
    const data = onAction.mock.calls[0][1] as { steps: Array<{ params: { max_value: unknown } }> };
    expect(data.steps[0].params.max_value).toBe(250);
  });

  it("marks an edited step so the reviewer can see what they changed", async () => {
    const user = userEvent.setup();
    await renderCard({ payload: makePayload() });

    await user.click(screen.getByRole("button", { name: /Edit step 1 settings/ }));
    await user.selectOptions(screen.getByLabelText(/Target column/), "amount");

    expect(screen.getByText("edited")).toBeInTheDocument();
    expect(screen.getByText(/· edited/)).toBeInTheDocument();
  });

  it("reorders steps and applies them in the new order", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(screen.getByRole("button", { name: /Move step 2 earlier/ }));
    await user.click(applyButton());

    await waitFor(() => expect(onAction).toHaveBeenCalled());
    const data = onAction.mock.calls[0][1] as { steps: Array<{ description: string }> };
    expect(data.steps.map((s) => s.description)).toEqual([
      "Step 2: drop header",
      "Step 1: strip",
    ]);
  });

  it("cannot move the first step earlier or the last step later", async () => {
    await renderCard({ payload: makePayload() });
    expect(screen.getByRole("button", { name: /Move step 1 earlier/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Move step 2 later/ })).toBeDisabled();
  });

  it("deletes a step outright", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(screen.getByRole("button", { name: /Delete step 2/ }));

    expect(screen.queryByText("Step 2: drop header")).not.toBeInTheDocument();
    await user.click(applyButton());
    await waitFor(() => expect(onAction).toHaveBeenCalled());
    expect((onAction.mock.calls[0][1] as { steps: unknown[] }).steps).toHaveLength(1);
  });

  it("adds a step the planner never proposed", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: makePayload(), onAction });

    await user.click(screen.getByRole("button", { name: /Add a step/ }));
    await user.click(screen.getByRole("button", { name: /^Strip whitespace$/ }));

    expect(screen.getByText("you added")).toBeInTheDocument();

    // A freshly added column-operation has no target yet, so it must block.
    expect(applyButton()).toBeDisabled();
    expect(screen.getByText(/needs a target column/i)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/Target column/), "amount");

    await waitFor(() => expect(applyButton()).toBeEnabled());
    await user.click(applyButton());
    await waitFor(() => expect(onAction).toHaveBeenCalled());
    const data = onAction.mock.calls[0][1] as { steps: Array<{ operation: string }> };
    expect(data.steps).toHaveLength(3);
    expect(data.steps[2].operation).toBe("strip_whitespace");
  });

  it("resets back to the plan as proposed", async () => {
    const user = userEvent.setup();
    await renderCard({ payload: makePayload() });

    await user.click(screen.getByRole("button", { name: /Delete step 2/ }));
    expect(screen.queryByText("Step 2: drop header")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Reset/ }));

    expect(screen.getByText("Step 2: drop header")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reset/ })).not.toBeInTheDocument();
  });

  it("warns on the steps that remove data", async () => {
    await renderCard({ payload: makePayload() });
    expect(screen.getAllByText("removes data").length).toBeGreaterThan(0);
  });
});

/* ── Refusing to apply something broken ─────────────────────────────────── */

describe("CleaningPlanCard — blocking a bad edit", () => {
  it("blocks Apply while a required value is missing and names it", async () => {
    await renderCard({
      payload: makePayload({
        steps: [
          {
            operation: "cap_extreme_values",
            column: "amount",
            params: {},
            description: "Step 1: cap",
          },
        ],
      }),
    });

    expect(applyButton()).toBeDisabled();
    expect(screen.getByText(/needs ceiling/i)).toBeInTheDocument();
    expect(screen.getByText(/1 thing to fix first/)).toBeInTheDocument();
  });

  it("blocks a step whose column is not in this dataset", async () => {
    await renderCard({
      payload: makePayload({
        steps: [
          {
            operation: "strip_whitespace",
            column: "gone_column",
            params: {},
            description: "Step 1",
          },
        ],
      }),
    });

    expect(screen.getByText(/'gone_column' does not exist/)).toBeInTheDocument();
    expect(applyButton()).toBeDisabled();
  });

  it("surfaces the server's own objection and does not dispatch", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    validatePlan.mockResolvedValue({
      valid: false,
      issues: [{ stepIndex: 1, field: "params", message: "drop_rows indices must be integers" }],
    });

    await renderCard({ payload: makePayload(), onAction });
    await user.click(applyButton());

    expect(await screen.findByText(/must be integers/)).toBeInTheDocument();
    expect(onAction).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Applied/ })).not.toBeInTheDocument();
  });

  it("still applies when the pre-flight check itself fails, letting apply report the error", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    validatePlan.mockRejectedValue(new Error("offline"));

    await renderCard({ payload: makePayload(), onAction });
    await user.click(applyButton());

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
  });
});

/* ── Recipes go through the same gate ───────────────────────────────────── */

describe("CleaningPlanCard — a saved recipe under review", () => {
  const recipePayload = () =>
    makePayload({
      recipeId: "recipe-7",
      recipeName: "Quarterly cleanup",
      summary: 'Saved recipe "Quarterly cleanup" — 2 steps, written against another dataset.',
    });

  it("names the recipe it came from", async () => {
    await renderCard({ payload: recipePayload() });
    expect(screen.getByText("Recipe: Quarterly cleanup")).toBeInTheDocument();
  });

  it("passes the recipe id through on apply, so the job records its provenance", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    await renderCard({ payload: recipePayload(), onAction });

    await user.click(applyButton());

    await waitFor(() => expect(onAction).toHaveBeenCalled());
    expect((onAction.mock.calls[0][1] as { recipeId?: string }).recipeId).toBe("recipe-7");
  });
});

/* ── Degrading when the catalogue cannot be loaded ──────────────────────── */

describe("CleaningPlanCard — without the operation catalogue", () => {
  it("says which half is unavailable and still allows include/exclude and apply", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    getOperationCatalog.mockRejectedValue(new Error("503"));

    render(<CleaningPlanCard payload={makePayload()} onAction={onAction} />);

    expect(await screen.findByText(/Step details are unavailable/)).toBeInTheDocument();
    await user.click(toggles()[1]);
    await user.click(screen.getByRole("button", { name: /^Apply 1 step$/ }));

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
  });
});
