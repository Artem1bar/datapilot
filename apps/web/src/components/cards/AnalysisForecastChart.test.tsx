import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalysisForecastChart } from "./AnalysisForecastChart";
import { toForecastView } from "@/lib/analysis-results";
import { ARIMA_STATISTICS, ARIMA_TABLE } from "@/test/analysis-fixtures";
import type { AnalysisForecastView } from "@/types";

// recharts measures its container, and jsdom reports every element as 0x0, so
// nothing would render. Substituting a fixed-size container is the only part of
// the library that is stubbed — the chart itself draws for real, which is what
// makes "the interval is on the page" a claim worth asserting.
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

function view(): AnalysisForecastView {
  const built = toForecastView(ARIMA_STATISTICS, ARIMA_TABLE);
  if (!built) throw new Error("fixture has no forecast");
  return built;
}

describe("AnalysisForecastChart", () => {
  it("draws the prediction interval as part of the default rendering", () => {
    // Not an option, not behind a toggle. A forecast line without its interval
    // states the opposite of what the model found.
    const { container } = render(<AnalysisForecastChart view={view()} />);
    expect(container.querySelector(".recharts-area-area")).not.toBeNull();
  });

  it("draws observed and forecast as visually distinct series", () => {
    const { container } = render(<AnalysisForecastChart view={view()} />);
    const curves = Array.from(
      container.querySelectorAll(".recharts-line-curve"),
    );

    expect(curves).toHaveLength(2);
    const dashed = curves.filter((curve) =>
      curve.getAttribute("stroke-dasharray"),
    );
    expect(dashed).toHaveLength(1);
    expect(curves[0].getAttribute("stroke")).not.toBe(
      curves[1].getAttribute("stroke"),
    );
  });

  it("labels all three marks and states what the band means", () => {
    render(<AnalysisForecastChart view={view()} />);

    expect(screen.getByText("Observed")).toBeInTheDocument();
    expect(screen.getByText("Forecast")).toBeInTheDocument();
    expect(screen.getByText("95% prediction interval")).toBeInTheDocument();
    expect(
      screen.getByText(
        /prediction interval for a future observation, not a confidence interval/,
      ),
    ).toBeInTheDocument();
  });

  it("states the horizon", () => {
    render(<AnalysisForecastChart view={view()} />);
    expect(screen.getByText(/3 periods ahead/)).toBeInTheDocument();
  });

  it("refuses to draw a forecast that arrived without an interval", () => {
    const bare = toForecastView({
      forecast: {
        periods: 1,
        level: 0.95,
        rows: [
          {
            horizon: 1,
            date: "2028-05-31T00:00:00",
            forecast: 48.866315,
            ci95_low: null,
            ci95_high: null,
          },
        ],
      },
    });
    const { container } = render(<AnalysisForecastChart view={bare!} />);

    expect(container.querySelector(".recharts-line-curve")).toBeNull();
    expect(
      screen.getByText(/without a prediction interval, so it is not drawn/),
    ).toBeInTheDocument();
  });

  it("falls back to a plain description of the band when the API sent none", () => {
    render(
      <AnalysisForecastChart
        view={{ ...view(), intervalMeaning: null, model: null, periods: 1 }}
      />,
    );
    expect(screen.getByText(/1 period ahead/)).toBeInTheDocument();
    expect(
      screen.getByText(/The shaded band is a prediction interval/),
    ).toBeInTheDocument();
  });
});
