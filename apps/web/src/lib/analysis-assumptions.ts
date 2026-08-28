/**
 * The three states an assumption check can be in, kept out of the components.
 *
 * `passed` arrives as `true`, `false`, or `null`, and the third value is not a
 * degenerate case of the other two: null means the check could not be run — too
 * few observations, no variance — which is not the same as a check that ran and
 * failed. Every surface that renders a check has to make all three visible, so
 * the mapping lives in one place rather than in each of them.
 */

import type { AnalysisAssumption } from "@/types";

export type AssumptionState = "passed" | "failed" | "unevaluated";

export function assumptionState(
  passed: boolean | null | undefined,
): AssumptionState {
  if (passed === true) return "passed";
  if (passed === false) return "failed";
  return "unevaluated";
}

/** How many checks landed in each state. */
export function assumptionTally(
  assumptions: readonly AnalysisAssumption[],
): Record<AssumptionState, number> {
  const tally: Record<AssumptionState, number> = {
    passed: 0,
    failed: 0,
    unevaluated: 0,
  };
  for (const assumption of assumptions)
    tally[assumptionState(assumption.passed)] += 1;
  return tally;
}

/** Failures first: a violated assumption undermines the finding it sits under,
 *  so it belongs where a reader who stops early will still see it. */
export function byWorstFirst(
  assumptions: readonly AnalysisAssumption[],
): AnalysisAssumption[] {
  const rank: Record<AssumptionState, number> = {
    failed: 0,
    unevaluated: 1,
    passed: 2,
  };
  return [...assumptions].sort(
    (a, b) => rank[assumptionState(a.passed)] - rank[assumptionState(b.passed)],
  );
}

/** Every assumption check across a set of operations, flattened. */
export function allAssumptions(
  operations: readonly {
    statistics?: { assumptions?: readonly AnalysisAssumption[] };
  }[],
): AnalysisAssumption[] {
  return operations.flatMap(
    (operation) => operation.statistics?.assumptions ?? [],
  );
}
