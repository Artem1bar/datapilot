import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorCard } from "./ErrorCard";
import type { ErrorCardPayload } from "@/types";

function makePayload(overrides: Partial<ErrorCardPayload> = {}): ErrorCardPayload {
  return {
    type: "error",
    title: "Cleaning failed",
    message: "The worker timed out.",
    ...overrides,
  };
}

describe("ErrorCard", () => {
  it("renders the title and message", () => {
    render(<ErrorCard payload={makePayload()} />);
    expect(screen.getByText("Cleaning failed")).toBeInTheDocument();
    expect(screen.getByText("The worker timed out.")).toBeInTheDocument();
  });

  it("shows no retry button when retry is absent", () => {
    render(<ErrorCard payload={makePayload()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("uses the retry label when provided", () => {
    render(
      <ErrorCard
        payload={makePayload({
          retry: { action: "apply_cleaning", data: { datasetId: "ds-1" }, label: "Retry cleaning" },
        })}
      />,
    );
    expect(screen.getByRole("button", { name: /retry cleaning/i })).toBeInTheDocument();
  });

  it("falls back to 'Try again' when no label is given", () => {
    render(<ErrorCard payload={makePayload({ retry: { action: "retry_clean_plan" } })} />);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("re-dispatches the retry action and data on click", async () => {
    const onAction = vi.fn();
    const data = { datasetId: "ds-1", steps: [{ operation: "strip_whitespace" }] };
    render(
      <ErrorCard
        payload={makePayload({ retry: { action: "apply_cleaning", data } })}
        onAction={onAction}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith("apply_cleaning", data);
  });
});
