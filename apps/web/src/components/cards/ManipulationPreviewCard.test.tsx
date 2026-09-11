import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManipulationPreviewCard } from "./ManipulationPreviewCard";
import type { ManipulationPreviewPayload } from "@/types";

const post = vi.fn();

vi.mock("@/lib/api", () => ({
  api: { post: (...args: unknown[]) => post(...args) },
}));

beforeEach(() => {
  post.mockReturnValue({
    json: () =>
      Promise.resolve({
        preview_before: [{ name: "  Alice ", city: "NYC" }],
        preview_after: [{ name: "Alice", city: "NYC" }],
        warnings: [],
        affected_row_count: 1,
      }),
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

function makePayload(overrides: Partial<ManipulationPreviewPayload> = {}): ManipulationPreviewPayload {
  return {
    type: "manipulation_preview",
    command: "trim names and drop the city column",
    datasetId: "ds-1",
    operations: [
      { opType: "format_column", params: { column: "name" }, description: "Trim spaces in name" },
      { opType: "delete_columns", params: { columns: ["city"] }, description: "Delete city" },
    ],
    previewBefore: [{ name: "  Alice ", city: "NYC" }],
    previewAfter: [{ name: "Alice" }],
    affectedColumns: ["name", "city"],
    affectedRowCount: 1,
    warnings: ["Deleting a column cannot be undone from here."],
    confirmationRequired: true,
    ...overrides,
  };
}

const toggles = () => screen.getAllByRole("button", { name: /this change/i });
const applyButton = () => screen.getByRole("button", { name: /^Apply|^Applied/ });

describe("ManipulationPreviewCard", () => {
  it("lists every operation with the command that produced them", () => {
    render(<ManipulationPreviewCard payload={makePayload()} />);

    expect(screen.getByText(/trim names and drop the city column/)).toBeInTheDocument();
    expect(screen.getByText("Trim spaces in name")).toBeInTheDocument();
    expect(screen.getByText("Delete city")).toBeInTheDocument();
    expect(toggles()).toHaveLength(2);
  });

  it("applies nothing until Apply is pressed", () => {
    const onAction = vi.fn();
    render(<ManipulationPreviewCard payload={makePayload()} onAction={onAction} />);
    expect(onAction).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });

  it("dispatches every operation when all are selected", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<ManipulationPreviewCard payload={makePayload()} onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: /^Apply 2 changes$/ }));

    expect(onAction).toHaveBeenCalledTimes(1);
    const [action, data] = onAction.mock.calls[0] as [string, Array<{ opType: string }>];
    expect(action).toBe("apply_manipulation");
    expect(data.map((op) => op.opType)).toEqual(["format_column", "delete_columns"]);
  });

  it("excluding an operation drops it from what is applied", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<ManipulationPreviewCard payload={makePayload()} onAction={onAction} />);

    await user.click(toggles()[1]);
    await waitFor(() => expect(applyButton()).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /^Apply 1 change$/ }));

    const data = onAction.mock.calls[0][1] as Array<{ opType: string }>;
    expect(data.map((op) => op.opType)).toEqual(["format_column"]);
  });

  it("re-previews on the server when the selection narrows", async () => {
    const user = userEvent.setup();
    render(<ManipulationPreviewCard payload={makePayload()} />);

    // The payload's own preview shows city already deleted.
    expect(screen.queryByText("city")).not.toBeInTheDocument();

    await user.click(toggles()[1]); // exclude the delete

    // The failure this prevents: still showing city gone after excluding the
    // very operation that deletes it.
    await waitFor(() => expect(screen.getByText("city")).toBeInTheDocument());
    expect(post).toHaveBeenCalledWith(
      "manipulation/ds-1/preview",
      expect.objectContaining({
        json: { operations: [expect.objectContaining({ op_type: "format_column" })] },
      }),
    );
  });

  it("restores the original preview without a request when everything is re-selected", async () => {
    const user = userEvent.setup();
    render(<ManipulationPreviewCard payload={makePayload()} />);

    await user.click(toggles()[1]);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    await user.click(toggles()[1]);

    await waitFor(() => expect(screen.queryByText("city")).not.toBeInTheDocument());
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("keeps the stale table but says so when the re-preview fails", async () => {
    const user = userEvent.setup();
    post.mockReturnValue({ json: () => Promise.reject(new Error("503")) });

    render(<ManipulationPreviewCard payload={makePayload()} />);
    await user.click(toggles()[1]);

    expect(await screen.findByText(/Couldn't refresh the preview/)).toBeInTheDocument();
    await waitFor(() => expect(applyButton()).toBeEnabled());
  });

  it("blocks Apply when nothing is selected", async () => {
    const user = userEvent.setup();
    render(<ManipulationPreviewCard payload={makePayload()} />);

    await user.click(toggles()[0]);
    await user.click(toggles()[1]);

    expect(screen.getByRole("button", { name: /^Apply 0 changes$/ })).toBeDisabled();
  });

  it("cancels without applying anything", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<ManipulationPreviewCard payload={makePayload()} onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: /Cancel/ }));

    expect(onAction).toHaveBeenCalledWith("cancel_manipulation");
  });

  it("shows the warnings that came with the preview", () => {
    render(<ManipulationPreviewCard payload={makePayload()} />);
    expect(screen.getByText(/cannot be undone/)).toBeInTheDocument();
  });

  it("locks after applying so the same edit cannot be dispatched twice", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<ManipulationPreviewCard payload={makePayload()} onAction={onAction} />);

    await user.click(applyButton());
    const applied = screen.getByRole("button", { name: /Applied/ });
    expect(applied).toBeDisabled();
    await user.click(applied);

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /Cancel/ })).not.toBeInTheDocument();
  });

  it("renders as applied when the payload says so, surviving a remount", () => {
    render(<ManipulationPreviewCard payload={makePayload({ applied: true })} />);
    expect(screen.getByRole("button", { name: /Applied/ })).toBeDisabled();
  });
});
