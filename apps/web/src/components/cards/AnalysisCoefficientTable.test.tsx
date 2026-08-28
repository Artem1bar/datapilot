import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { AnalysisCoefficientTable } from "./AnalysisCoefficientTable";
import { toRegressionView } from "@/lib/analysis-results";
import {
  COUNT_STATISTICS,
  LOGIT_STATISTICS,
  OLS_STATISTICS,
} from "@/test/analysis-fixtures";
import type { AnalysisRegressionView, AnalysisStatistics } from "@/types";

function view(statistics: AnalysisStatistics): AnalysisRegressionView {
  const built = toRegressionView(statistics);
  if (!built) throw new Error("fixture has no coefficients");
  return built;
}

/** The row of the coefficient table whose term cell contains `text`. */
function rowFor(text: string | RegExp): HTMLElement {
  const cell = screen.getByText(text);
  const row = cell.closest("tr");
  if (!row) throw new Error(`no row for ${text}`);
  return row;
}

describe("AnalysisCoefficientTable", () => {
  it("reads as a regression table, not a generic grid", () => {
    render(<AnalysisCoefficientTable view={view(OLS_STATISTICS)} />);

    for (const header of [
      "Term",
      "Estimate",
      "Std. error",
      "t",
      "p",
      "95% CI",
    ]) {
      expect(
        screen.getByRole("columnheader", { name: header }),
      ).toBeInTheDocument();
    }
    const tenure = rowFor("tenure");
    expect(within(tenure).getByText("2.4485")).toBeInTheDocument();
    expect(within(tenure).getByText("0.0667")).toBeInTheDocument();
    expect(within(tenure).getByText("36.7161")).toBeInTheDocument();
    expect(within(tenure).getByText("[2.3164, 2.5806]")).toBeInTheDocument();
  });

  it("names the omitted reference level in the table body", () => {
    // A coefficient table whose baseline is unnamed cannot be interpreted:
    // region[North] is a difference from something, and this is the something.
    render(<AnalysisCoefficientTable view={view(OLS_STATISTICS)} />);

    const reference = rowFor("East");
    expect(within(reference).getByText(/reference level/)).toBeInTheDocument();
    expect(reference.compareDocumentPosition(rowFor("North"))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("marks significance once, without a ladder of stars", () => {
    render(<AnalysisCoefficientTable view={view(OLS_STATISTICS)} />);

    // All four OLS coefficients clear 0.05, at p-values spanning ninety orders
    // of magnitude — a star ladder would encode that as a difference in kind.
    expect(
      screen.getAllByLabelText("significant at the 5% level"),
    ).toHaveLength(4);
    expect(screen.queryByText(/\*/)).not.toBeInTheDocument();
    expect(screen.getByText(/A marked row has p < 0.05/)).toBeInTheDocument();
  });

  it("leaves a coefficient with no p-value unmarked rather than guessing", () => {
    const unmarked: AnalysisStatistics = {
      coefficients: [
        { term: "x", coefficient: 1.5, std_err: 0.2, p_value: null },
      ],
    };
    render(<AnalysisCoefficientTable view={view(unmarked)} />);
    expect(
      screen.queryByLabelText("significant at the 5% level"),
    ).not.toBeInTheDocument();
  });

  it("keeps a tiny p-value readable instead of rounding it to zero", () => {
    render(<AnalysisCoefficientTable view={view(OLS_STATISTICS)} />);
    expect(within(rowFor("West")).getByText("4.13e-7")).toBeInTheDocument();
  });

  it("shows the odds ratio and its interval for a logit", () => {
    render(<AnalysisCoefficientTable view={view(LOGIT_STATISTICS)} />);

    expect(
      screen.getByRole("columnheader", { name: "Odds ratio" }),
    ).toBeInTheDocument();
    const dose = rowFor("dose");
    expect(within(dose).getByText("1.8653")).toBeInTheDocument();
    expect(within(dose).getByText("[1.485, 2.343]")).toBeInTheDocument();
  });

  it("labels the count model's ratio column as a rate ratio", () => {
    render(<AnalysisCoefficientTable view={view(COUNT_STATISTICS)} />);
    expect(
      screen.getByRole("columnheader", { name: "Rate ratio (IRR)" }),
    ).toBeInTheDocument();
  });

  it("renders a statistic the backend could not compute as an em dash", () => {
    // Never "null", never a zero standing in for a missing measurement.
    render(<AnalysisCoefficientTable view={view(COUNT_STATISTICS)} />);

    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
    expect(screen.getByText("Pseudo R²").parentElement).toHaveTextContent("—");
  });

  it("survives a payload carrying no fit statistics or diagnostics", () => {
    const bare: AnalysisStatistics = {
      coefficients: [{ term: "x", coefficient: null, p_value: null }],
    };
    render(<AnalysisCoefficientTable view={view(bare)} />);

    expect(rowFor("x")).toBeInTheDocument();
    expect(screen.queryByText(/High collinearity/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Standard errors:/)).not.toBeInTheDocument();
  });

  it("reports the standard error family the fit used", () => {
    render(<AnalysisCoefficientTable view={view(OLS_STATISTICS)} />);
    expect(screen.getByText(/Standard errors: HC3/)).toBeInTheDocument();
  });

  it("warns when a regressor's variance inflation makes it unidentified", () => {
    const collinear: AnalysisStatistics = {
      ...OLS_STATISTICS,
      vif: [
        { term: "tenure", vif: 1.01 },
        { term: "experience", vif: 42.7 },
      ],
    };
    render(<AnalysisCoefficientTable view={view(collinear)} />);
    expect(screen.getByText(/High collinearity/)).toHaveTextContent(
      "experience (VIF 42.7)",
    );
  });
});
