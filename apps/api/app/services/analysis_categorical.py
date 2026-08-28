"""Tier 3: tests over counts and proportions.

Chi-square and the proportion z-test answer the categorical half of "is the
difference real" — whether two categorical variables move together, and whether
a rate differs between groups or from a hypothesized value. They share the
reporting contract of the mean comparisons in
:mod:`app.services.analysis_inference`: statistic, p-value, effect size,
confidence interval, assumption checks, and n.

One deliberate omission: goodness-of-fit tests against a uniform distribution
only. Accepting a hypothesized distribution would mean accepting a list of
numbers from the model, and the invariant that makes this pipeline trustworthy
is that the model never supplies a value.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analysis_prep import (
    alternative_of,
    assumptions,
    directional_suffix,
    exclusion_note,
    interval_sidedness,
    keyed_groups,
    require_two_groups,
    significant,
)
from app.services.analysis_result import ExecutionError, OperationResult, frame_to_result
from app.services.analysis_stats import (
    check_expected_counts,
    cohens_h,
    cohens_w,
    cramers_v,
    effect_size,
    interval,
    proportion_difference_ci,
    wilson_ci,
)


def _chi_square_independence(
    df: pd.DataFrame, params: dict[str, Any], label: str
) -> OperationResult:
    row_col, col_col = params["row"], params["column"]
    for name in (row_col, col_col):
        if name not in df.columns:
            raise ExecutionError(f"column {name!r} is not in the dataset")

    frame = df[[row_col, col_col]].dropna()
    excluded = len(df) - len(frame)
    observed = pd.crosstab(frame[row_col], frame[col_col])
    # An all-zero row or column carries no information and makes the test
    # undefined, so drop it rather than let scipy raise.
    observed = observed.loc[observed.sum(axis=1) > 0, observed.sum(axis=0) > 0]
    if observed.shape[0] < 2 or observed.shape[1] < 2:
        raise ExecutionError(
            f"chi_square: needs at least two categories in each of {row_col!r} and {col_col!r}; "
            f"got a {observed.shape[0]}x{observed.shape[1]} table"
        )

    corrected = stats.chi2_contingency(observed)
    uncorrected = stats.chi2_contingency(observed, correction=False)
    applied_correction = observed.shape == (2, 2)
    total = int(observed.to_numpy().sum())

    payload: dict[str, Any] = {
        "test": f"Chi-square test of independence ({row_col} x {col_col})",
        "statistic": float(corrected.statistic),
        "dof": int(corrected.dof),
        "p_value": float(corrected.pvalue),
        "significant_at_0.05": significant(float(corrected.pvalue)),
        "continuity_correction": applied_correction,
        "table_shape": f"{observed.shape[0]}x{observed.shape[1]}",
        "effect_size": effect_size(
            "Cramér's V",
            cramers_v(float(uncorrected.statistic), total, *observed.shape),
            "correlation",
            computed_from="the uncorrected chi-square, by convention",
        ),
        "assumptions": assumptions(check_expected_counts(corrected.expected_freq)),
    }
    if applied_correction:
        odds_ratio, fisher_p = stats.fisher_exact(observed.to_numpy())
        # An odds ratio is meaningless without knowing which way round the
        # table is, and the orientation here comes from sorting the category
        # labels — not from anything the user said. State it, so 6.0 cannot be
        # read as 1/6.
        rows_, columns_ = list(observed.index), list(observed.columns)
        payload["fisher_exact"] = {
            "odds_ratio": float(odds_ratio),
            "p_value": float(fisher_p),
            "orientation": (
                f"odds of {col_col}={columns_[0]!r} rather than {columns_[1]!r}, "
                f"in {row_col}={rows_[0]!r} relative to {rows_[1]!r}"
            ),
            "note": "exact test; prefer it over chi-square when expected counts are small",
        }

    flat = observed.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    notes = exclusion_note(excluded)
    if applied_correction:
        notes.append("Yates' continuity correction applied (2x2 table).")
    return frame_to_result(
        flat,
        op="chi_square",
        label=label,
        n=total,
        n_excluded=excluded,
        notes=notes,
        stats_payload=payload,
    )


def _chi_square_goodness_of_fit(
    df: pd.DataFrame, params: dict[str, Any], label: str
) -> OperationResult:
    column = params["column"]
    if column not in df.columns:
        raise ExecutionError(f"column {column!r} is not in the dataset")

    counts = df[column].value_counts(dropna=True).sort_index()
    excluded = int(df[column].isna().sum())
    if len(counts) < 2:
        raise ExecutionError(
            f"chi_square: {column!r} has {len(counts)} distinct value(s); "
            f"a goodness-of-fit test needs at least two categories"
        )

    total = int(counts.sum())
    expected = total / len(counts)
    result = stats.chisquare(counts.to_numpy(dtype=float))

    frame = pd.DataFrame(
        {
            column: [str(index) for index in counts.index],
            "observed": counts.to_numpy(dtype=int),
            "expected": [expected] * len(counts),
        }
    )
    payload = {
        "test": f"Chi-square goodness of fit for {column} against a uniform distribution",
        "statistic": float(result.statistic),
        "dof": int(len(counts) - 1),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "expected_per_category": float(expected),
        "effect_size": effect_size(
            "Cohen's w", cohens_w(float(result.statistic), total), "correlation"
        ),
        "assumptions": assumptions(
            check_expected_counts(np.full(len(counts), expected, dtype=float))
        ),
    }
    return frame_to_result(
        frame,
        op="chi_square",
        label=label,
        n=total,
        n_excluded=excluded,
        notes=exclusion_note(excluded)
        + [
            "Tested against a uniform distribution — equal counts in every category. "
            "This pipeline does not accept a hypothesized distribution from the model, "
            "because the model does not supply numbers."
        ],
        stats_payload=payload,
    )


_CHI_SQUARE_KINDS = {
    "independence": _chi_square_independence,
    "goodness_of_fit": _chi_square_goodness_of_fit,
}


def op_chi_square(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    kind = params.get("kind")
    handler = _CHI_SQUARE_KINDS.get(str(kind))
    if handler is None:
        raise ExecutionError(
            f"chi_square: unknown kind {kind!r} (allowed: {sorted(_CHI_SQUARE_KINDS)})"
        )
    if "column" not in params:
        raise ExecutionError("chi_square: missing required parameter 'column'")
    if kind == "independence" and "row" not in params:
        raise ExecutionError("chi_square: a test of independence requires 'row'")
    return handler(df, params, label)


def _success_counts(series: pd.Series, success_value: Any) -> tuple[int, int]:
    """Count successes and total, matching on the string form of the value."""
    as_text = series.astype(str)
    return int((as_text == str(success_value)).sum()), int(series.size)


def op_proportion_test(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column = params["column"]
    if column not in df.columns:
        raise ExecutionError(f"column {column!r} is not in the dataset")
    if "success_value" not in params:
        raise ExecutionError("proportion_test: requires 'success_value'")
    success_value = params["success_value"]

    present = df[column].dropna()
    categories = sorted({str(value) for value in present.unique()})
    if str(success_value) not in categories:
        raise ExecutionError(
            f"proportion_test: {success_value!r} does not occur in {column!r}. "
            f"Values present: {categories[:20]}"
        )

    group_by = params.get("group_by")
    if group_by is not None:
        return _proportion_two_sample(df, column, success_value, group_by, params, label)
    if "p0" not in params:
        raise ExecutionError(
            "proportion_test: without 'group_by' this is a one-sample test, which "
            "requires 'p0', the hypothesized proportion"
        )
    return _proportion_one_sample(df, column, success_value, float(params["p0"]), params, label)


def _proportion_one_sample(
    df: pd.DataFrame,
    column: str,
    success_value: Any,
    p0: float,
    params: dict[str, Any],
    label: str,
) -> OperationResult:
    if not 0.0 < p0 < 1.0:
        raise ExecutionError(f"proportion_test: p0 must be between 0 and 1, got {p0}")
    alternative = alternative_of(params)

    present = df[column].dropna()
    successes, n = _success_counts(present, success_value)
    excluded = len(df) - n
    if n < 1:
        raise ExecutionError(f"proportion_test: no non-null values in {column!r}")

    proportion = successes / n
    standard_error = math.sqrt(p0 * (1 - p0) / n)
    z = (proportion - p0) / standard_error if standard_error > 0 else math.nan
    p_value = _z_p_value(z, alternative)
    low, high = wilson_ci(successes, n)

    frame = pd.DataFrame(
        [
            {
                column: str(success_value),
                "n": n,
                "successes": successes,
                "proportion": proportion,
                "ci95_low": low,
                "ci95_high": high,
                "tested_against": p0,
            }
        ]
    )
    payload = {
        "test": (
            f"One-sample z-test for a proportion ({column} == {success_value!r}) "
            f"against {p0:g}{directional_suffix(alternative)}"
        ),
        "alternative": alternative,
        "statistic": z,
        "p_value": p_value,
        "significant_at_0.05": significant(p_value),
        "proportion": proportion,
        "confidence_interval": interval(
            low,
            high,
            of="the proportion",
            method="Wilson score",
            **interval_sidedness(alternative),
        ),
        "effect_size": effect_size("Cohen's h", cohens_h(proportion, p0), "cohen_d"),
        "assumptions": assumptions(
            check_expected_counts(np.array([n * p0, n * (1 - p0)], dtype=float))
        ),
    }
    return frame_to_result(
        frame,
        op="proportion_test",
        label=label,
        n=n,
        n_excluded=excluded,
        notes=exclusion_note(excluded),
        stats_payload=payload,
    )


def _proportion_two_sample(
    df: pd.DataFrame,
    column: str,
    success_value: Any,
    group_by: str,
    params: dict[str, Any],
    label: str,
) -> OperationResult:
    if group_by not in df.columns:
        raise ExecutionError(f"column {group_by!r} is not in the dataset")
    alternative = alternative_of(params)

    frame = df[[group_by, column]].dropna()
    excluded = len(df) - len(frame)
    # One keyed grouping, for the reason spelled out in
    # :func:`app.services.analysis_prep.keyed_groups`: listing labels from
    # unique() while selecting rows by their string form turns 1 and "1" into
    # two groups whose masks each select both groups' rows.
    keyed = keyed_groups(frame, group_by, column)
    labels = [group_label for group_label, _ in keyed]
    require_two_groups(labels, "proportion_test")

    counts = [_success_counts(values, success_value) for _, values in keyed]
    (successes1, n1), (successes2, n2) = counts
    if n1 < 1 or n2 < 1:
        raise ExecutionError("proportion_test: both groups need at least one observation")

    p1, p2 = successes1 / n1, successes2 / n2
    pooled = (successes1 + successes2) / (n1 + n2)
    standard_error = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / standard_error if standard_error > 0 else math.nan
    p_value = _z_p_value(z, alternative)
    low, high = proportion_difference_ci(successes1, n1, successes2, n2)

    rows = []
    for group_label, (successes, n) in zip(labels, counts, strict=True):
        ci_low, ci_high = wilson_ci(successes, n)
        rows.append(
            {
                group_by: group_label,
                "n": n,
                "successes": successes,
                "proportion": successes / n,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
            }
        )

    payload = {
        "test": (
            f"Two-proportion z-test for {column} == {success_value!r} "
            f"({labels[0]} vs {labels[1]}){directional_suffix(alternative)}"
        ),
        "alternative": alternative,
        "comparison": f"{labels[0]} minus {labels[1]}",
        "statistic": z,
        "p_value": p_value,
        "significant_at_0.05": significant(p_value),
        "difference": p1 - p2,
        "confidence_interval": interval(
            low,
            high,
            of="the difference in proportions",
            method="Newcombe",
            **interval_sidedness(alternative),
        ),
        "effect_size": effect_size("Cohen's h", cohens_h(p1, p2), "cohen_d"),
        "assumptions": assumptions(
            check_expected_counts(
                np.array(
                    [n1 * pooled, n1 * (1 - pooled), n2 * pooled, n2 * (1 - pooled)], dtype=float
                )
            )
        ),
    }
    return frame_to_result(
        pd.DataFrame(rows),
        op="proportion_test",
        label=label,
        n=n1 + n2,
        n_excluded=excluded,
        notes=exclusion_note(excluded),
        stats_payload=payload,
    )


def _z_p_value(z: float, alternative: str) -> float:
    if not math.isfinite(z):
        return math.nan
    if alternative == "greater":
        return float(stats.norm.sf(z))
    if alternative == "less":
        return float(stats.norm.cdf(z))
    return float(2 * stats.norm.sf(abs(z)))


# Registered into the executor's dispatch table.
CATEGORICAL_OPERATIONS = {
    "chi_square": op_chi_square,
    "proportion_test": op_proportion_test,
}
