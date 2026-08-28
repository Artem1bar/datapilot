import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalysisWeightedEstimate } from "./AnalysisWeightedEstimate";
import { toWeightedView } from "@/lib/analysis-results";
import {
  DESIGN_EFFECT_STATISTICS,
  GROUPED_WEIGHTED_STATISTICS,
  WEIGHTED_CROSSTAB_STATISTICS,
  WEIGHTED_MEAN_STATISTICS,
} from "@/test/analysis-fixtures";
import type { AnalysisStatistics, AnalysisWeightedView } from "@/types";

function view(statistics: AnalysisStatistics): AnalysisWeightedView {
  const built = toWeightedView(statistics);
  if (!built) throw new Error("fixture has no survey design");
  return built;
}

/** The figure block whose label is `label`. */
function figure(label: string): HTMLElement {
  const element = screen.getByText(label).parentElement;
  if (!element) throw new Error(`no figure for ${label}`);
  return element;
}

describe("AnalysisWeightedEstimate", () => {
  it("shows the weighted estimate beside the unweighted one", () => {
    render(<AnalysisWeightedEstimate view={view(WEIGHTED_MEAN_STATISTICS)} />);

    expect(figure("Weighted mean")).toHaveTextContent("42.5");
    expect(figure("Unweighted mean")).toHaveTextContent("35");
    expect(
      screen.getByText(/Weighting moved the estimate by 7.5/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/only the weighted one estimates the population/),
    ).toBeInTheDocument();
  });

  it("shows the standard error and interval that go with the estimate", () => {
    render(<AnalysisWeightedEstimate view={view(WEIGHTED_MEAN_STATISTICS)} />);

    expect(figure("Standard error")).toHaveTextContent("6.4791");
    expect(figure("95% CI")).toHaveTextContent("[25.8449, 59.1551]");
  });

  it("makes the effective sample size legible beside the response count", () => {
    // "Your 6 responses are worth 4.8" is the insight this tier exists for.
    render(<AnalysisWeightedEstimate view={view(DESIGN_EFFECT_STATISTICS)} />);

    expect(figure("Respondents")).toHaveTextContent("6");
    expect(figure("Effective sample size")).toHaveTextContent("4.8");
    expect(figure("Design effect")).toHaveTextContent("0.89");
    expect(
      screen.getByText(/6 responses carry the statistical weight of about 4.8/),
    ).toBeInTheDocument();
  });

  it("switches to the total's labels for a weighted total", () => {
    render(
      <AnalysisWeightedEstimate
        view={view({
          design: WEIGHTED_MEAN_STATISTICS.design,
          weighted_total: 510,
          unweighted_sum: 210,
          estimated_population: 12,
        })}
      />,
    );
    expect(figure("Weighted total")).toHaveTextContent("510");
    expect(figure("Unweighted sum")).toHaveTextContent("210");
    expect(screen.getByText(/The weights sum to 12/)).toBeInTheDocument();
  });

  it("contrasts the design-corrected chi-square with the naive one", () => {
    render(
      <AnalysisWeightedEstimate view={view(WEIGHTED_CROSSTAB_STATISTICS)} />,
    );

    expect(screen.getByText(/Rao-Scott χ² = 14.0524/)).toBeInTheDocument();
    expect(screen.getByText(/χ² = 28.9426/)).toBeInTheDocument();
    expect(
      screen.getByText(/commonest error in published survey analysis/),
    ).toBeInTheDocument();
  });

  it("describes the sampling design the estimate assumed", () => {
    render(<AnalysisWeightedEstimate view={view(WEIGHTED_MEAN_STATISTICS)} />);
    expect(
      screen.getByText(/weights w · unstratified · unclustered · 5 df/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Taylor linearization/)).toBeInTheDocument();
  });

  it("renders a grouped estimate without inventing a headline pair", () => {
    // Every estimate lives in the result table; there is no single weighted
    // mean to show, so none is shown.
    render(
      <AnalysisWeightedEstimate view={view(GROUPED_WEIGHTED_STATISTICS)} />,
    );

    expect(screen.queryByText("Weighted mean")).not.toBeInTheDocument();
    expect(screen.queryByText("Effective sample size")).not.toBeInTheDocument();
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Weighted mean of score, using w as the design weight/),
    ).toBeInTheDocument();
  });

  it("renders an uncomputable statistic as an em dash", () => {
    render(
      <AnalysisWeightedEstimate
        view={view({
          design: WEIGHTED_MEAN_STATISTICS.design,
          weighted_mean: 42.5,
          unweighted_mean: null,
          standard_error: null,
          effective_sample_size: null,
          design_effect_kish: 1.25,
        })}
      />,
    );
    expect(figure("Unweighted mean")).toHaveTextContent("—");
    expect(figure("Effective sample size")).toHaveTextContent("—");
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
  });
});
