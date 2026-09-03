import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScatterPlot } from "./ScatterPlot";
import type { ChartConfig } from "@/types";

// recharts measures its container, and jsdom reports every element as 0x0, so
// nothing would render. Only the container is stubbed; the chart draws for
// real, which is what makes "the points are on numeric axes" worth asserting.
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

function config(overrides: Partial<ChartConfig> = {}): ChartConfig {
  return {
    chart_type: "scatter",
    title: "revenue vs units",
    x_field: "units",
    y_field: "revenue",
    data: [
      { x: 0, y: 1, group: "West" },
      { x: 1, y: 2, group: "East" },
      { x: 100, y: 101, group: "West" },
    ],
    options: {
      computed: true,
      n: 3,
      plotted: 3,
      total_points: 3,
      sampled: false,
      group_field: "region",
      groups: ["East", "West"],
      fit: { slope: 1, intercept: 1, r_squared: 0.98, p_value: 0.004 },
    },
    ...overrides,
  };
}

/** Horizontal position of each drawn point, in render order. */
function markX(container: HTMLElement): number[] {
  return Array.from(container.querySelectorAll(".recharts-scatter-symbol")).map(
    (mark) => {
      const path = mark.querySelector("path");
      const transform = path?.getAttribute("transform") ?? "";
      const match = /translate\(([-\d.]+)/.exec(transform);
      if (!match) throw new Error(`no translate on ${transform}`);
      return Number(match[1]);
    },
  );
}

describe("ScatterPlot", () => {
  it("draws one mark per point on a numeric x axis", () => {
    const { container } = render(
      <ScatterPlot
        config={config({
          data: [
            { x: 0, y: 1 },
            { x: 1, y: 2 },
            { x: 100, y: 101 },
          ],
          options: {},
        })}
      />,
    );
    const xs = markX(container);
    expect(xs).toHaveLength(3);
    // On a category axis the three x values would be evenly spaced. On a
    // numeric axis, 0 and 1 sit almost on top of each other next to 100.
    expect(xs[1] - xs[0]).toBeLessThan((xs[2] - xs[1]) / 10);
  });

  it("draws the fitted line the API computed as a reference segment", () => {
    const { container } = render(<ScatterPlot config={config()} />);
    expect(container.querySelector(".recharts-reference-line")).not.toBeNull();
  });

  it("does not draw a line when the API sent no fit", () => {
    const { container } = render(
      <ScatterPlot config={config({ options: {} })} />,
    );
    expect(container.querySelector(".recharts-reference-line")).toBeNull();
  });

  it("colors groups as separate series and names them", () => {
    const { container } = render(<ScatterPlot config={config()} />);
    expect(container.querySelectorAll(".recharts-scatter")).toHaveLength(2);
    expect(screen.getByText("East")).toBeInTheDocument();
    expect(screen.getByText("West")).toBeInTheDocument();
  });

  it("draws the missing-label bucket in gray, never in a group hue", () => {
    const { container } = render(
      <ScatterPlot
        config={config({
          data: [
            { x: 0, y: 1, group: "East" },
            { x: 1, y: 2, group: "(missing)" },
          ],
          options: { groups: ["East", "(missing)"], group_field: "region" },
        })}
      />,
    );
    const fills = Array.from(
      container.querySelectorAll(".recharts-scatter-symbol path"),
    ).map((path) => path.getAttribute("fill"));
    expect(fills).toContain("#9CA3AF");
    expect(fills.filter((fill) => fill === "#9CA3AF")).toHaveLength(1);
  });

  it("labels the axes with the column names", () => {
    render(<ScatterPlot config={config()} />);
    expect(screen.getByText("units")).toBeInTheDocument();
    expect(screen.getByText("revenue")).toBeInTheDocument();
  });

  it("states the fit and the denominator under the chart", () => {
    render(<ScatterPlot config={config()} />);
    expect(screen.getByText(/n = 3/)).toBeInTheDocument();
    expect(screen.getByText(/R² = 0\.98/)).toBeInTheDocument();
    expect(screen.getByText(/revenue = 1 × units \+ 1/)).toBeInTheDocument();
  });

  it("says when the chart is a sample of the points", () => {
    render(
      <ScatterPlot
        config={config({
          options: {
            n: 4812,
            plotted: 3,
            total_points: 4812,
            sampled: true,
            fit: { slope: 1, intercept: 1 },
          },
        })}
      />,
    );
    expect(
      screen.getByText(/random sample of 3 of 4,812 points/),
    ).toBeInTheDocument();
  });

  it("names the groups that fall outside the sample", () => {
    render(
      <ScatterPlot
        config={config({
          options: {
            groups: ["East", "West", "rare"],
            unplotted_groups: ["rare"],
            sampled: true,
            plotted: 3,
            total_points: 50000,
          },
        })}
      />,
    );
    expect(screen.getByText(/no points from rare/i)).toBeInTheDocument();
    // Still in the legend: the group exists even though the sample missed it.
    expect(screen.getByText("rare")).toBeInTheDocument();
  });

  it("draws bubbles whose area follows the size column", () => {
    const { container } = render(
      <ScatterPlot
        config={config({
          chart_type: "bubble",
          data: [
            { x: 0, y: 1, size: 1 },
            { x: 1, y: 2, size: 10 },
            { x: 2, y: 3, size: 100 },
          ],
          options: { size_field: "orders", size_range: [1, 100] },
        })}
      />,
    );
    const shapes = new Set(
      Array.from(container.querySelectorAll(".recharts-scatter-symbol path")).map(
        (path) => path.getAttribute("d"),
      ),
    );
    expect(shapes.size).toBe(3);
    expect(screen.getByText(/bubble area shows orders/i)).toBeInTheDocument();
    expect(screen.getByText(/1 to 100/)).toBeInTheDocument();
  });

  it("draws equal marks when nothing sizes the points", () => {
    const { container } = render(<ScatterPlot config={config()} />);
    const shapes = new Set(
      Array.from(container.querySelectorAll(".recharts-scatter-symbol path")).map(
        (path) => path.getAttribute("d"),
      ),
    );
    expect(shapes.size).toBe(1);
  });

  it("says when nothing can be plotted", () => {
    render(<ScatterPlot config={config({ data: [] })} />);
    expect(screen.getByText(/no plottable points/i)).toBeInTheDocument();
  });
});
