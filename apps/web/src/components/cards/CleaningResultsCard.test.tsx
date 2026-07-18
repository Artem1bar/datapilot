import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CleaningResultsCard } from "./CleaningResultsCard";
import type { CleaningResultsPayload } from "@/types";

function makePayload(overrides: Partial<CleaningResultsPayload> = {}): CleaningResultsPayload {
  return {
    type: "cleaning_results",
    downloadUrl: "/api/v1/cleaning/job-1/download",
    rowsBefore: 15,
    rowsAfter: 13,
    issuesResolved: 25,
    datasetId: "ds-1",
    jobId: "job-1",
    ...overrides,
  };
}

describe("CleaningResultsCard — trust UX actions", () => {
  it("offers compare, save-as-recipe, and revert when a job id is present", () => {
    render(<CleaningResultsCard payload={makePayload()} />);
    expect(screen.getByRole("button", { name: /see what changed/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save as recipe/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revert to original/i })).toBeInTheDocument();
  });

  it("hides the trust actions when the payload has no job id (legacy cards)", () => {
    render(<CleaningResultsCard payload={makePayload({ jobId: undefined })} />);
    expect(screen.queryByRole("button", { name: /see what changed/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save as recipe/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /revert to original/i })).not.toBeInTheDocument();
  });

  it("dispatches compare_cleaning with the job id", async () => {
    const onAction = vi.fn();
    render(<CleaningResultsCard payload={makePayload()} onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: /see what changed/i }));
    expect(onAction).toHaveBeenCalledWith("compare_cleaning", { jobId: "job-1" });
  });

  it("dispatches revert_cleaning with job and message ids", async () => {
    const onAction = vi.fn();
    render(<CleaningResultsCard payload={makePayload()} messageId="msg-9" onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: /revert to original/i }));
    expect(onAction).toHaveBeenCalledWith("revert_cleaning", { jobId: "job-1", messageId: "msg-9" });
  });

  it("shows the reverted badge and hides the revert button once reverted", () => {
    render(<CleaningResultsCard payload={makePayload({ reverted: true })} />);
    expect(screen.getByText(/reverted/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /revert to original/i })).not.toBeInTheDocument();
  });

  it("saves a recipe through the name dialog", async () => {
    const onAction = vi.fn();
    render(<CleaningResultsCard payload={makePayload()} messageId="msg-9" onAction={onAction} />);

    await userEvent.click(screen.getByRole("button", { name: /save as recipe/i }));
    await userEvent.type(screen.getByPlaceholderText(/standard orders cleanup/i), "My recipe");
    await userEvent.click(screen.getByRole("button", { name: /^save recipe$/i }));

    expect(onAction).toHaveBeenCalledWith("save_recipe", {
      jobId: "job-1",
      name: "My recipe",
      messageId: "msg-9",
    });
  });

  it("blocks saving with an empty name", async () => {
    const onAction = vi.fn();
    render(<CleaningResultsCard payload={makePayload()} onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: /save as recipe/i }));
    expect(screen.getByRole("button", { name: /^save recipe$/i })).toBeDisabled();
  });

  it("shows the saved state instead of the save button after saving", () => {
    render(<CleaningResultsCard payload={makePayload({ savedRecipeName: "My recipe" })} />);
    expect(screen.getByText(/saved as/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save as recipe/i })).not.toBeInTheDocument();
  });
});
