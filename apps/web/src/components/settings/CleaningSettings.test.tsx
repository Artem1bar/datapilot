import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CleaningSettings } from "./CleaningSettings";
import * as settingsApi from "@/lib/settings-api";
import type { UserPreferences } from "@/lib/settings-api";

vi.mock("@/lib/settings-api");

const DEFAULTS: UserPreferences = {
  cleaning_aggressiveness: "standard",
  outlier_method: "mad",
  outlier_threshold: 3.5,
  cap_strategy: "auto",
  null_fill_default: "none",
  dedup_default: false,
  domain: "auto",
  custom_instructions: "",
  ai_sample_size: 500,
  max_remediation_rounds: 2,
  review_first: true,
  cleaning_model: null,
  verification_model: null,
};

describe("CleaningSettings", () => {
  beforeEach(() => {
    vi.mocked(settingsApi.getSettings).mockResolvedValue({ ...DEFAULTS });
    vi.mocked(settingsApi.updateSettings).mockImplementation((p) =>
      Promise.resolve({ ...DEFAULTS, ...p }),
    );
  });

  it("loads preferences and renders the form", async () => {
    render(<CleaningSettings />);
    expect(await screen.findByText("Cleaning aggressiveness")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save changes/ })).toBeInTheDocument();
  });

  it("saves edited preferences and confirms", async () => {
    const user = userEvent.setup();
    render(<CleaningSettings />);
    const textarea = await screen.findByPlaceholderText(/Always keep/);
    await user.type(textarea, "keep raw");
    await user.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => expect(settingsApi.updateSettings).toHaveBeenCalledTimes(1));
    const arg = vi.mocked(settingsApi.updateSettings).mock.calls[0][0];
    expect(arg.custom_instructions).toContain("keep raw");
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("shows an error when loading fails", async () => {
    vi.mocked(settingsApi.getSettings).mockRejectedValue(new Error("boom"));
    render(<CleaningSettings />);
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});
