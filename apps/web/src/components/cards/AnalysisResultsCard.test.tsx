import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalysisResultsCard } from "./AnalysisResultsCard";
import { CardRenderer } from "./CardRenderer";
import { toResultsCard } from "@/lib/analysis-results";
import {
  ARIMA_OPERATION,
  ARIMA_TABLE,
  DESIGN_EFFECT_OPERATION,
  OLS_OPERATION,
  OLS_TABLE,
} from "@/test/analysis-fixtures";
import type { AnalysisResultsPayload } from "@/types";

// See AnalysisForecastChart.test.tsx: jsdom reports every element as 0x0, so
// recharts would draw nothing without a fixed-size container.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  const { cloneElement, isValidElement } = await import("react");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) =>
      isValidElement<{ width: number; height: number }>(children)
        ? cloneElement(children, { width: 600, height: 300 })
        : children,
  };
});

function payload(
  ...args: Parameters<typeof toResultsCard>
): AnalysisResultsPayload {
  const card = toResultsCard(...args);
  if (!card) throw new Error("fixture produced no results card");
  return card;
}

describe("AnalysisResultsCard", () => {
  it("names each operation and its denominator", () => {
    render(
      <AnalysisResultsCard payload={payload([OLS_OPERATION], [OLS_TABLE])} />,
    );

    expect(screen.getByText("Salary on tenure and region")).toBeInTheDocument();
    expect(screen.getByText("ols")).toBeInTheDocument();
    expect(screen.getByText(/n\s*=\s*120 \(8 excluded\)/)).toBeInTheDocument();
  });

  it("renders the coefficient table for a fitted model", () => {
    render(
      <AnalysisResultsCard payload={payload([OLS_OPERATION], [OLS_TABLE])} />,
    );
    expect(
      screen.getByRole("columnheader", { name: "Estimate" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/reference level/)).toBeInTheDocument();
  });

  it("shows every assumption state without any interaction", async () => {
    // The scope document calls surfacing these the line between a statistics
    // tool and a plausible-looking one. A check behind a disclosure is a check
    // most readers never see.
    render(
      <AnalysisResultsCard payload={payload([OLS_OPERATION], [OLS_TABLE])} />,
    );

    const passed = screen.getByText(/all below 10/).closest("div");
    const failed = screen.getByText(/residual spread varies/).closest("div");
    const unevaluated = screen
      .getByText(/Cook's distance could not be computed/)
      .closest("div");

    expect(passed?.className).toContain("emerald");
    expect(failed?.className).toContain("amber");
    expect(unevaluated?.className).not.toContain("amber");
    expect(unevaluated?.className).not.toContain("emerald");

    // Colour alone would put the distinction out of reach; each state is named.
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("not evaluated")).toBeInTheDocument();
  });

  it("puts a failed assumption above the ones that passed", () => {
    render(
      <AnalysisResultsCard payload={payload([OLS_OPERATION], [OLS_TABLE])} />,
    );

    const failed = screen.getByText(/residual spread varies/);
    const passed = screen.getByText(/all below 10/);
    expect(failed.compareDocumentPosition(passed)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("renders the forecast chart with its interval", async () => {
    const { container } = render(
      <AnalysisResultsCard
        payload={payload([ARIMA_OPERATION], [ARIMA_TABLE])}
      />,
    );

    // The chart is code-split, so it arrives on a later tick — and resolving
    // that chunk pulls recharts in, which under a loaded worker takes longer
    // than the one-second default findBy allows.
    expect(
      await screen.findByText("95% prediction interval", undefined, {
        timeout: 10_000,
      }),
    ).toBeInTheDocument();
    expect(container.querySelector(".recharts-area-area")).not.toBeNull();
  });

  it("renders a survey estimate beside its unweighted counterpart", () => {
    render(
      <AnalysisResultsCard payload={payload([DESIGN_EFFECT_OPERATION], [])} />,
    );

    expect(screen.getByText("Weighted mean").parentElement).toHaveTextContent(
      "42.5",
    );
    expect(screen.getByText("Unweighted mean").parentElement).toHaveTextContent(
      "35",
    );
    expect(
      screen.getByText("Effective sample size").parentElement,
    ).toHaveTextContent("4.8");
  });

  it("renders the operation's notes", () => {
    render(
      <AnalysisResultsCard payload={payload([OLS_OPERATION], [OLS_TABLE])} />,
    );
    expect(
      screen.getByText(/Categorical baselines: region = 'East'/),
    ).toBeInTheDocument();
  });

  it("is reachable through the card renderer", () => {
    render(<CardRenderer payload={payload([OLS_OPERATION], [OLS_TABLE])} />);
    expect(screen.getByText("Statistical results")).toBeInTheDocument();
  });

  it("survives an operation whose statistics are all null", () => {
    const empty = {
      ...OLS_OPERATION,
      statistics: {
        coefficients: [
          {
            term: "x",
            coefficient: null,
            std_err: null,
            p_value: null,
            ci_low: null,
            ci_high: null,
          },
        ],
        assumptions: [],
      },
    };
    render(<AnalysisResultsCard payload={payload([empty], [])} />);

    expect(screen.getByText("x")).toBeInTheDocument();
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
  });
});
