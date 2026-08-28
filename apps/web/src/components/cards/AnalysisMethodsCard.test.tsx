import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalysisMethodsCard } from "./AnalysisMethodsCard";
import { toCodeScripts, toMethodsCard } from "@/lib/analysis-methods";
import { RAW_CODE } from "@/test/analysis-fixtures";
import type { AnalysisMethodsPayload } from "@/types";

function makePayload(
  overrides: Partial<AnalysisMethodsPayload> = {},
): AnalysisMethodsPayload {
  return {
    type: "analysis_methods",
    question: "Did the treatment work?",
    dataset: { filename: "trial.csv", rows: 600, columns: 5 },
    operations: [
      {
        index: 0,
        op: "ttest",
        label: "Score by arm",
        params: { kind: "independent", column: "score", group_by: "arm" },
        n: 575,
        n_excluded: 25,
        notes: ["Excluded 25 row(s) with missing values."],
        statistics: {
          test: "Welch's t-test (control vs treatment, unequal variance)",
          statistic: -4.981626,
          p_value: 8.37e-7,
          effect_size: {
            name: "Cohen's d",
            value: -0.415059,
            magnitude: "small",
          },
          confidence_interval: {
            low: -6.999136,
            high: -3.040683,
            level: 0.95,
            of: "the difference in mean score",
          },
          assumptions: [
            {
              name: "Equal variance across groups",
              passed: true,
              detail: "Levene's test p = 0.1777",
              statistic: 1.82,
              p_value: 0.1777,
            },
            {
              name: "Expected cell counts",
              passed: false,
              detail: "2 of 4 cells have an expected count below 5",
              statistic: 0.75,
              p_value: null,
            },
            {
              name: "Complete pairs",
              passed: null,
              detail: "25 incomplete pair(s) were dropped",
              statistic: 575,
              p_value: null,
            },
          ],
        },
      },
    ],
    environment: {
      python: "3.12.7",
      pandas: "2.3.1",
      numpy: "2.1.0",
      scipy: "1.18.1",
    },
    multipleComparisons: null,
    methodsNote: "## Methods\n\nEverything was computed deterministically.",
    code: [],
    ...overrides,
  };
}

describe("AnalysisMethodsCard", () => {
  it("summarizes the analysis without being expanded", () => {
    render(<AnalysisMethodsCard payload={makePayload()} />);
    expect(
      screen.getByText(/1 operation over 600 rows of trial\.csv/),
    ).toBeInTheDocument();
    // Detail stays out of the way until asked for.
    expect(screen.queryByText(/Welch's t-test/)).not.toBeInTheDocument();
  });

  it("reveals the test, effect size and interval when expanded", async () => {
    const user = userEvent.setup();
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));

    expect(screen.getByText(/Welch's t-test/)).toBeInTheDocument();
    expect(screen.getByText(/Cohen's d = -0\.4151/)).toBeInTheDocument();
    expect(
      screen.getByText(/95% CI for the difference in mean score/),
    ).toBeInTheDocument();
  });

  it("states the denominator including excluded rows", async () => {
    const user = userEvent.setup();
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));
    expect(screen.getByText(/n\s*=\s*575 \(25 excluded\)/)).toBeInTheDocument();
  });

  it("keeps a tiny p-value readable instead of rounding it to zero", async () => {
    const user = userEvent.setup();
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));
    expect(screen.getByText(/p 8\.37e-7/)).toBeInTheDocument();
  });

  it("distinguishes a failed assumption from one that could not be evaluated", async () => {
    const user = userEvent.setup();
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));

    // Collapsing "not evaluated" into "passed" would let an untested
    // assumption read as a satisfied one.
    const failed = screen.getByText(/2 of 4 cells/).closest("div");
    const unevaluated = screen.getByText(/25 incomplete pair/).closest("div");
    expect(failed?.className).toContain("amber");
    expect(unevaluated?.className).not.toContain("amber");
    expect(unevaluated?.className).not.toContain("emerald");
  });

  it("shows the multiple-comparison adjustment when several tests ran", async () => {
    const user = userEvent.setup();
    render(
      <AnalysisMethodsCard
        payload={makePayload({
          multipleComparisons: {
            method: "Benjamini-Hochberg",
            controls: "false discovery rate",
            n_tests: 3,
            tests: [
              {
                label: "Score by arm",
                test: "Welch",
                p_value: 0.01,
                p_value_adjusted: 0.03,
              },
            ],
          },
        })}
      />,
    );
    await user.click(screen.getByRole("button", { name: /methods/i }));
    expect(
      screen.getByText(/3 tests were run against this dataset/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Score by arm: p 0\.01 → adjusted 0\.03/),
    ).toBeInTheDocument();
  });

  it("states that no figure came from a language model", async () => {
    const user = userEvent.setup();
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));
    expect(
      screen.getByText(/no value here was produced by a language model/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/scipy 1\.18\.1/)).toBeInTheDocument();
  });

  it("copies the methods note", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    // userEvent.setup() installs its own clipboard stub, and jsdom exposes
    // navigator.clipboard as a getter — so override after setup, by descriptor.
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));
    await user.click(
      screen.getByRole("button", { name: /copy methods note/i }),
    );
    expect(writeText).toHaveBeenCalledWith(
      "## Methods\n\nEverything was computed deterministically.",
    );
  });
});

describe("toMethodsCard", () => {
  const raw = {
    question: "Did it work?",
    dataset: { filename: "trial.csv", rows: 600, columns: 5 },
    operations: [makePayload().operations[0]],
    environment: {
      python: "3.12.7",
      pandas: "2.3.1",
      numpy: "2.1.0",
      scipy: "1.18.1",
    },
    methods_note: "## Methods",
  };

  it("maps the API record onto the card payload", () => {
    const card = toMethodsCard(raw);
    expect(card?.dataset.rows).toBe(600);
    expect(card?.environment.scipy).toBe("1.18.1");
    expect(card?.methodsNote).toBe("## Methods");
  });

  it("returns null when the analysis was refused or failed", () => {
    // No computation happened, so there is nothing to account for.
    expect(toMethodsCard(null)).toBeNull();
    expect(toMethodsCard(undefined)).toBeNull();
    expect(toMethodsCard({ ...raw, operations: [] })).toBeNull();
  });

  it("tolerates a response from an API that does not send provenance", () => {
    expect(toMethodsCard({} as never)).toBeNull();
  });

  it("carries the exported scripts through to the card", () => {
    const card = toMethodsCard({ ...raw, code: RAW_CODE });
    expect(card?.code.map((script) => script.language)).toEqual([
      "python",
      "r",
    ]);
    expect(card?.code[1].incomplete).toEqual(["quantile_regression"]);
  });

  it("leaves the card usable when the API sent no code", () => {
    // Historical sessions predate code export; the note still stands alone.
    expect(toMethodsCard(raw)?.code).toEqual([]);
  });
});

describe("AnalysisMethodsCard code export", () => {
  it("offers the script beside the methods note", async () => {
    const user = userEvent.setup();
    render(
      <AnalysisMethodsCard
        payload={makePayload({ code: toCodeScripts(RAW_CODE) })}
      />,
    );

    // Collapsed, the card is a summary; the script is detail like the rest.
    expect(
      screen.queryByRole("button", { name: "Python" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /methods/i }));

    expect(screen.getByRole("button", { name: "Python" })).toBeInTheDocument();
    expect(screen.getByText(/import pandas as pd/)).toBeInTheDocument();
  });

  it("renders no export controls for a session that has no code", async () => {
    const user = userEvent.setup();
    render(<AnalysisMethodsCard payload={makePayload()} />);
    await user.click(screen.getByRole("button", { name: /methods/i }));

    expect(
      screen.queryByRole("button", { name: /copy .* script/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /copy methods note/i }),
    ).toBeInTheDocument();
  });
});

describe("AnalysisMethodsCard collapsed state", () => {
  it("states a failed assumption before the card is opened", () => {
    // The fixture carries one failed check and one that could not be evaluated.
    render(<AnalysisMethodsCard payload={makePayload()} />);
    expect(
      screen.getByText(/1 assumption failed · 1 could not be evaluated/),
    ).toBeInTheDocument();
  });

  it("says nothing when every check passed", () => {
    const clean = makePayload();
    const [operation] = clean.operations;
    render(
      <AnalysisMethodsCard
        payload={makePayload({
          operations: [
            {
              ...operation,
              statistics: {
                ...operation.statistics,
                assumptions: [
                  {
                    name: "Equal variance across groups",
                    passed: true,
                    detail: "Levene's test p = 0.1777",
                    statistic: 1.82,
                    p_value: 0.1777,
                  },
                ],
              },
            },
          ],
        })}
      />,
    );
    expect(
      screen.queryByText(/could not be evaluated/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/assumption failed/)).not.toBeInTheDocument();
  });
});
