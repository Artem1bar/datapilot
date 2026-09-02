import { describe, it, expect } from "vitest";
import {
  NOT_COMPUTED,
  formatCount,
  formatInterval,
  formatLevel,
  formatPValue,
  formatStatistic,
  isSignificant,
} from "./analysis-format";

describe("formatStatistic", () => {
  it("renders a statistic that could not be computed as an em dash", () => {
    // The backend sends null for a statistic it could not compute. Rendering
    // that as "null" or as 0 would both be claims the data does not support.
    for (const missing of [null, undefined, NaN, Infinity, -Infinity]) {
      expect(formatStatistic(missing)).toBe(NOT_COMPUTED);
    }
  });

  it("drops trailing zeros rather than implying precision", () => {
    expect(formatStatistic(2)).toBe("2");
    expect(formatStatistic(2.5)).toBe("2.5");
    expect(formatStatistic(0)).toBe("0");
  });

  it("rounds to four decimals by default", () => {
    expect(formatStatistic(2.448504)).toBe("2.4485");
    expect(formatStatistic(-5.368749)).toBe("-5.3687");
  });

  it("keeps significant figures on a magnitude four decimals would erase", () => {
    // analysis_stats.json_safe goes out of its way to preserve these; rounding
    // them here would throw away exactly what it kept.
    expect(formatStatistic(4.1256e-7)).toBe("4.13e-7");
    expect(formatStatistic(1.65052e-94)).toBe("1.65e-94");
  });

  it("switches to exponent notation for magnitudes fixed decimals cannot carry", () => {
    expect(formatStatistic(1.23e12)).toBe("1.23e+12");
  });
});

describe("formatPValue", () => {
  it("never renders a p-value as zero", () => {
    expect(formatPValue(8.37e-7)).toBe("8.37e-7");
    expect(formatPValue(5e-324)).toBe("4.94e-324");
  });

  it("renders an absent p-value as an em dash", () => {
    expect(formatPValue(null)).toBe(NOT_COMPUTED);
  });
});

describe("formatCount", () => {
  it("groups whole counts and keeps one decimal on fractional ones", () => {
    expect(formatCount(2000)).toBe("2,000");
    expect(formatCount(1240.37)).toBe("1,240.4");
    expect(formatCount(null)).toBe(NOT_COMPUTED);
  });
});

describe("formatInterval", () => {
  it("renders both bounds", () => {
    expect(formatInterval(2.316421, 2.580587)).toBe("[2.3164, 2.5806]");
  });

  it("renders no interval at all when either bound is missing", () => {
    // Half an interval is not an interval.
    expect(formatInterval(2.3, null)).toBe(NOT_COMPUTED);
    expect(formatInterval(null, 2.5)).toBe(NOT_COMPUTED);
  });
});

describe("formatLevel", () => {
  it("renders a confidence level as a percentage", () => {
    expect(formatLevel(0.95)).toBe("95%");
    expect(formatLevel(0.99)).toBe("99%");
  });

  it("falls back to the conventional level when none was sent", () => {
    expect(formatLevel(undefined)).toBe("95%");
  });
});

describe("isSignificant", () => {
  it("decides at the conventional level", () => {
    expect(isSignificant(0.049)).toBe(true);
    expect(isSignificant(0.05)).toBe(false);
  });

  it("returns null when there is no p-value to decide on", () => {
    // Unknown is not the same as "not significant".
    expect(isSignificant(null)).toBeNull();
    expect(isSignificant(undefined)).toBeNull();
  });
});
