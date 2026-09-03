import { describe, it, expect } from "vitest";
import {
  MAX_COLOR_GROUPS,
  describeScatterRequest,
  fitSegment,
  scatterColumns,
  scatterSeries,
  toScatterView,
} from "./scatter";
import type { ChartConfig } from "@/types";

/** The config the API builds for a colored scatter, as it arrives. */
function config(overrides: Partial<ChartConfig> = {}): ChartConfig {
  return {
    chart_type: "scatter",
    title: "revenue vs units",
    x_field: "units",
    y_field: "revenue",
    data: [
      { x: 1, y: 10, group: "West" },
      { x: 2, y: 21, group: "East" },
      { x: 3, y: 29, group: "West" },
    ],
    options: {
      computed: true,
      n: 3,
      n_excluded: 0,
      plotted: 3,
      total_points: 3,
      sampled: false,
      sample_seed: null,
      group_field: "region",
      groups: ["East", "West"],
      fit: {
        slope: 9.5,
        intercept: 1,
        r: 0.99,
        r_squared: 0.98,
        p_value: 0.01,
        std_err: 0.5,
      },
    },
    ...overrides,
  };
}

describe("toScatterView", () => {
  it("reads the points, the groups and the fit the API computed", () => {
    const view = toScatterView(config());
    expect(view).not.toBeNull();
    expect(view?.xField).toBe("units");
    expect(view?.yField).toBe("revenue");
    expect(view?.points).toEqual([
      { x: 1, y: 10, group: "West", size: null },
      { x: 2, y: 21, group: "East", size: null },
      { x: 3, y: 29, group: "West", size: null },
    ]);
    expect(view?.groupField).toBe("region");
    expect(view?.groups).toEqual(["East", "West"]);
    expect(view?.fit).toEqual({
      slope: 9.5,
      intercept: 1,
      rSquared: 0.98,
      pValue: 0.01,
    });
    expect(view?.n).toBe(3);
    expect(view?.plotted).toBe(3);
    expect(view?.totalPoints).toBe(3);
    expect(view?.sampled).toBe(false);
  });

  it("keeps points without a group when the chart is not colored", () => {
    const view = toScatterView(
      config({
        data: [
          { x: 1, y: 2 },
          { x: 2, y: 4 },
        ],
        options: { computed: true, n: 2, groups: [], group_field: null },
      }),
    );
    expect(view?.points.map((p) => p.group)).toEqual([null, null]);
    expect(view?.groups).toEqual([]);
    expect(view?.groupField).toBeNull();
    expect(view?.fit).toBeNull();
  });

  it("skips rows without numeric coordinates", () => {
    const view = toScatterView(
      config({
        data: [
          { x: 1, y: 2 },
          { x: null, y: 3 },
          { x: "4", y: 5 },
          { x: 6, y: Number.NaN },
        ],
      }),
    );
    expect(view?.points).toHaveLength(1);
  });

  it("accepts field-named rows from the planner path", () => {
    const view = toScatterView(
      config({ data: [{ units: 1, revenue: 2 }], options: {} }),
    );
    expect(view?.points).toEqual([{ x: 1, y: 2, group: null, size: null }]);
  });

  it("returns null when nothing can be plotted", () => {
    expect(toScatterView(config({ data: [] }))).toBeNull();
  });

  it("derives groups from the points when the options carry none", () => {
    const view = toScatterView(
      config({
        data: [
          { x: 1, y: 1, group: "(missing)" },
          { x: 2, y: 2, group: "b" },
          { x: 3, y: 3, group: "a" },
        ],
        options: {},
      }),
    );
    expect(view?.groups).toEqual(["a", "b", "(missing)"]);
  });

  it("ignores a fit that is not numeric", () => {
    const view = toScatterView(
      config({ options: { fit: { slope: null, intercept: 1 } } }),
    );
    expect(view?.fit).toBeNull();
  });
});

describe("fitSegment", () => {
  it("spans the plotted x range using the API's slope and intercept", () => {
    const view = toScatterView(config());
    expect(view && fitSegment(view)).toEqual([
      { x: 1, y: 10.5 },
      { x: 3, y: 29.5 },
    ]);
  });

  it("is null without a fit", () => {
    const view = toScatterView(config({ options: {} }));
    expect(view && fitSegment(view)).toBeNull();
  });

  it("is null when every point shares one x", () => {
    const view = toScatterView(
      config({
        data: [
          { x: 2, y: 1 },
          { x: 2, y: 3 },
        ],
      }),
    );
    expect(view && fitSegment(view)).toBeNull();
  });
});

describe("scatterSeries", () => {
  it("splits the points by group in legend order", () => {
    const view = toScatterView(config());
    const series = view ? scatterSeries(view) : [];
    expect(series.map((s) => s.name)).toEqual(["East", "West"]);
    expect(series[1].points).toHaveLength(2);
  });

  it("is one unnamed series when the chart is not colored", () => {
    const view = toScatterView(
      config({ data: [{ x: 1, y: 2 }], options: {} }),
    );
    const series = view ? scatterSeries(view) : [];
    expect(series).toHaveLength(1);
    expect(series[0].name).toBeNull();
  });
});

describe("scatterColumns", () => {
  const profile = {
    columns: {
      units: { dtype: "int64", unique_count: 40 },
      revenue: { dtype: "float64", unique_count: 50 },
      region: { dtype: "object", unique_count: 3 },
      customer_id: { dtype: "object", unique_count: 500 },
      flag: { dtype: "bool", unique_count: 2 },
      when: { dtype: "datetime64[ns]", unique_count: 5 },
      score: { dtype: "Float64", unique_count: MAX_COLOR_GROUPS + 1 },
    },
  };

  it("offers numeric columns as axes and low-cardinality columns as colors, alphabetically", () => {
    // The profile arrives in JSONB key order (length, then bytes), which is
    // no order a reader can predict; the lists are sorted by name instead.
    const choices = scatterColumns(profile);
    expect(choices.numeric.map((c) => c.name)).toEqual([
      "revenue",
      "score",
      "units",
    ]);
    expect(choices.categorical.map((c) => c.name)).toEqual(["flag", "region"]);
  });

  it("handles a missing or malformed profile", () => {
    expect(scatterColumns(null)).toEqual({ numeric: [], categorical: [] });
    expect(scatterColumns({ columns: "nope" })).toEqual({
      numeric: [],
      categorical: [],
    });
  });
});

describe("describeScatterRequest", () => {
  it("names the axes the way the API's provenance does", () => {
    expect(
      describeScatterRequest({ x: "units", y: "revenue", colorBy: null, size: null }),
    ).toBe("Scatter plot of revenue against units");
    expect(
      describeScatterRequest({ x: "units", y: "revenue", colorBy: "region", size: null }),
    ).toBe("Scatter plot of revenue against units, colored by region");
  });
});

describe("toScatterView — groups the sample does not show", () => {
  it("keeps them in the legend and names them", () => {
    const view = toScatterView(
      config({
        data: [{ x: 1, y: 1, group: "common" }],
        options: {
          groups: ["common", "rare"],
          unplotted_groups: ["rare"],
          sampled: true,
          total_points: 50000,
        },
      }),
    );
    expect(view?.groups).toEqual(["common", "rare"]);
    expect(view?.unplottedGroups).toEqual(["rare"]);
  });

  it("defaults to none", () => {
    expect(toScatterView(config())?.unplottedGroups).toEqual([]);
  });
});


describe("toScatterView — bubble size and interpretation", () => {
  it("reads the size of each point and the range the API measured", () => {
    const view = toScatterView(
      config({
        chart_type: "bubble",
        data: [
          { x: 1, y: 10, size: 5 },
          { x: 2, y: 21, size: 50 },
        ],
        options: { size_field: "orders", size_range: [5, 50] },
      }),
    );
    expect(view?.sizeField).toBe("orders");
    expect(view?.sizeRange).toEqual([5, 50]);
    expect(view?.points.map((p) => p.size)).toEqual([5, 50]);
  });

  it("has no size without a size field", () => {
    const view = toScatterView(config());
    expect(view?.sizeField).toBeNull();
    expect(view?.sizeRange).toBeNull();
    expect(view?.points[0].size).toBeNull();
  });

  it("parses the reading the API computed", () => {
    const view = toScatterView(
      config({
        options: {
          interpretation: {
            direction: "positive",
            strength: "strong",
            significant: true,
            summary: ["A strong positive linear association."],
            caveats: ["Association is not causation."],
            next_steps: [{ question: "Is it?", why: "Because." }],
          },
        },
      }),
    );
    expect(view?.interpretation).toEqual({
      direction: "positive",
      strength: "strong",
      significant: true,
      summary: ["A strong positive linear association."],
      caveats: ["Association is not causation."],
      nextSteps: [{ question: "Is it?", why: "Because." }],
    });
  });

  it("has no reading when the API sent none or a malformed one", () => {
    expect(toScatterView(config({ options: {} }))?.interpretation).toBeNull();
    expect(
      toScatterView(config({ options: { interpretation: { summary: "nope" } } }))
        ?.interpretation,
    ).toBeNull();
  });
});

describe("describeScatterRequest — size", () => {
  it("names the size after the color, as the API does", () => {
    expect(
      describeScatterRequest({ x: "units", y: "revenue", colorBy: "region", size: "orders" }),
    ).toBe("Scatter plot of revenue against units, colored by region, sized by orders");
    expect(
      describeScatterRequest({ x: "units", y: "revenue", colorBy: null, size: "orders" }),
    ).toBe("Scatter plot of revenue against units, sized by orders");
  });
});
