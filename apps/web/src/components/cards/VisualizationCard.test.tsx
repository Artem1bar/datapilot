import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { VisualizationCard } from "./VisualizationCard";
import type { VisualizationPayload } from "@/types";

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

const payload: VisualizationPayload = {
  type: "visualization",
  chart: {
    chart_type: "scatter",
    title: "revenue vs units",
    x_field: "units",
    y_field: "revenue",
    data: [
      { x: 1, y: 10 },
      { x: 2, y: 21 },
      { x: 3, y: 29 },
    ],
    options: { computed: true, n: 3, fit: { slope: 9.5, intercept: 1 } },
  },
  description: "Plotted on request.",
};

const reading = {
  direction: "positive",
  strength: "strong",
  significant: true,
  summary: ["A strong positive linear association: higher units goes with higher revenue (r = 0.99)."],
  caveats: ["Association is not causation: a third factor could drive both."],
  next_steps: [
    {
      question: "What is the Spearman correlation between units and revenue?",
      why: "Rank-based, so a few extreme points cannot dominate.",
    },
  ],
};

describe("VisualizationCard — reading the plot", () => {
  it("shows what the plot says, the caveats, and questions to ask next", async () => {
    const onAction = vi.fn();
    render(
      <VisualizationCard
        payload={{
          ...payload,
          chart: { ...payload.chart, options: { ...payload.chart.options, interpretation: reading } },
        }}
        onAction={onAction}
      />,
    );
    expect(await screen.findByText(/reading this plot/i, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/strong positive linear association/)).toBeInTheDocument();
    expect(screen.getByText(/not causation/)).toBeInTheDocument();

    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(
      screen.getByRole("button", { name: /Spearman correlation/ }),
    );
    expect(onAction).toHaveBeenCalledWith(
      "ask",
      "What is the Spearman correlation between units and revenue?",
    );
  });

  it("renders a chart without a reading as before", async () => {
    render(<VisualizationCard payload={payload} />);
    await screen.findByText("revenue vs units", undefined, { timeout: 5000 });
    expect(screen.queryByText(/reading this plot/i)).toBeNull();
  });
});

describe("VisualizationCard", () => {
  it("renders the chart in the conversation", async () => {
    const { container } = render(<VisualizationCard payload={payload} />);
    // The chart module is lazy-loaded, so the title arrives on the next tick.
    expect(
      await screen.findByText("revenue vs units", undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".recharts-scatter-symbol")).toHaveLength(3);
    expect(screen.getByText("Plotted on request.")).toBeInTheDocument();
  });
});
