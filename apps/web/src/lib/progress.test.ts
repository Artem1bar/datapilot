import { describe, it, expect } from "vitest";
import { progressStageLabel } from "./progress";

describe("progressStageLabel", () => {
  it.each([
    [0, "Preparing data..."],
    [19, "Preparing data..."],
    [20, "Applying cleaning steps..."],
    [54, "Applying cleaning steps..."],
    [55, "Verifying results & fixing issues..."],
    [79, "Verifying results & fixing issues..."],
    [80, "Finalizing cleaned file..."],
    [100, "Finalizing cleaned file..."],
  ])("maps %i%% to %j", (progress, label) => {
    expect(progressStageLabel(progress)).toBe(label);
  });
});
