"""Shared preparation for the inferential operations.

Splitting a numeric column by a grouping column, dropping the rows that are
missing either, and summarizing what came back is the same work for every
Tier 3 test. It lives here so that :mod:`app.services.analysis_inference` and
:mod:`app.services.analysis_categorical` share one definition of "the groups"
rather than two that can drift apart.

The ordering rule matters more than it looks: groups come back in sorted label
order, so the sign of every reported difference is stable and explainable
("groups in alphabetical order") instead of depending on row order in the
uploaded file.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analysis_result import ExecutionError
from app.services.analysis_stats import ALPHA, CONFIDENCE_LEVEL, Assumption, mean_ci

ALTERNATIVES = ("two-sided", "less", "greater")

# Minimum observations a group needs before a test over it means anything.
MIN_GROUP_N = 2


def alternative_of(params: dict[str, Any]) -> str:
    alternative = params.get("alternative", "two-sided")
    if alternative not in ALTERNATIVES:
        raise ExecutionError(f"unknown alternative {alternative!r} (allowed: {list(ALTERNATIVES)})")
    return str(alternative)


def directional_suffix(alternative: str) -> str:
    """The direction, for a test's name. Empty for a two-sided test.

    A directional test is a different claim from a two-sided one, and the
    ``test`` string is what the narrator quotes. Leaving the direction only in
    a separate ``alternative`` field lets "significantly greater" be written
    beside a name that does not say the test was one-sided.
    """
    return "" if alternative == "two-sided" else f", one-sided ({alternative})"


def interval_sidedness(alternative: str) -> dict[str, str]:
    """Labels that keep a directional test and its two-sided interval legible.

    Both numbers are correct and they can disagree: at 0.025 < p < 0.05 a
    one-sided test rejects while the two-sided 95% interval still spans zero.
    Measured on real data — p = 0.046 beside [-0.15, 1.90] — and the narrator
    is told to report the p-value *and* to use the interval, so unlabelled it
    writes a sentence that contradicts itself.

    The interval stays two-sided rather than becoming a one-sided bound. The
    interval builders (``mean_ci``, ``mean_difference_ci``, ``wilson_ci``,
    ``proportion_difference_ci``) are shared, audited, and agree with
    scipy/statsmodels to 1e-10; forking each of them per-alternative would put
    four more branches under the part of this codebase that most needs to stay
    checkable. A half-open bound is also less informative to a reader than a
    range — and infinity is not JSON. So the interval is labelled for what it
    is, and the mismatch is explained where a reader will meet it.
    """
    if alternative == "two-sided":
        return {"sided": "two-sided"}
    return {
        "sided": "two-sided",
        "caveat": (
            f"the test is one-sided ({alternative}) while this interval is two-sided at "
            f"{int(CONFIDENCE_LEVEL * 100)}%, so the interval can span zero while the test "
            f"rejects; read it as the range of values compatible with the data, not as the "
            f"test"
        ),
    }


def numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        raise ExecutionError(f"column {column!r} is not in the dataset")
    return pd.to_numeric(df[column], errors="coerce")


def exclusion_note(excluded: int) -> list[str]:
    return [f"Excluded {excluded} row(s) with missing values."] if excluded else []


def keyed_groups(frame: pd.DataFrame, group_by: str, column: str) -> list[tuple[str, pd.Series]]:
    """Group *column* by the string form of *group_by*, every row in one group.

    A single keyed grouping rather than "list the labels, then select each with
    a mask". Two distinct values with the same string form — an object-dtype
    column holding both ``1`` and ``"1"``, which a real Excel round-trip
    produces — would otherwise yield a duplicate label, and each duplicate's
    mask selects *all* matching rows. Those rows then enter the statistic twice
    while the reported n counts them once, so the degrees of freedom, the sums
    of squares and the denominator describe three different datasets. With only
    ``{1, "1"}`` present it is worse: two labels pass the two-group check and a
    group is Welch-tested against itself.

    ``sort=True`` keeps the sorted-label ordering the callers guarantee, which
    the sign of every reported difference depends on.
    """
    grouped = frame.groupby(frame[group_by].astype(str), sort=True)[column]
    return [(str(key), values) for key, values in grouped]


def split_groups(
    df: pd.DataFrame, group_by: str, column: str
) -> tuple[list[str], list[np.ndarray], int, int]:
    """Split *column* by *group_by*, dropping rows missing either.

    Groups come back in sorted label order so the sign of every reported
    difference is stable and explainable ("groups in alphabetical order")
    rather than dependent on row order in the uploaded file.
    """
    if group_by not in df.columns:
        raise ExecutionError(f"column {group_by!r} is not in the dataset")
    frame = pd.DataFrame({group_by: df[group_by], column: numeric_series(df, column)}).dropna()
    used, excluded = len(frame), len(df) - len(frame)

    keyed = keyed_groups(frame, group_by, column)
    labels = [label for label, _ in keyed]
    groups = [values.to_numpy(dtype=float) for _, values in keyed]
    return labels, groups, used, excluded


def require_two_groups(labels: list[str], op: str) -> None:
    if len(labels) == 2:
        return
    if len(labels) < 2:
        raise ExecutionError(
            f"{op}: needs exactly two groups, found {len(labels)} "
            f"({labels or 'none'}) after dropping missing values"
        )
    raise ExecutionError(
        f"{op}: needs exactly two groups, found {len(labels)} ({labels[:5]}). "
        f"Use anova (or kruskal, if the data are not normal) to compare more than two groups."
    )


def require_group_sizes(labels: list[str], groups: list[np.ndarray], op: str) -> None:
    too_small = [
        label for label, values in zip(labels, groups, strict=True) if values.size < MIN_GROUP_N
    ]
    if too_small:
        raise ExecutionError(
            f"{op}: group(s) {too_small} have fewer than {MIN_GROUP_N} observations"
        )


def group_summary(labels: list[str], groups: list[np.ndarray], group_by: str) -> pd.DataFrame:
    """Per-group means with 95% intervals — the table behind a mean comparison."""
    rows = []
    for label, values in zip(labels, groups, strict=True):
        low, high = mean_ci(values)
        rows.append(
            {
                group_by: label,
                "n": int(values.size),
                "mean": float(values.mean()),
                "sd": float(values.std(ddof=1)) if values.size > 1 else None,
                "median": float(np.median(values)),
                "ci95_low": low,
                "ci95_high": high,
            }
        )
    return pd.DataFrame(rows)


def rank_summary(labels: list[str], groups: list[np.ndarray], group_by: str) -> pd.DataFrame:
    """Per-group medians and mean ranks — the table behind a rank-based test."""
    combined = np.concatenate(groups) if groups else np.array([])
    ranks = stats.rankdata(combined) if combined.size else np.array([])
    rows, offset = [], 0
    for label, values in zip(labels, groups, strict=True):
        size = values.size
        group_ranks = ranks[offset : offset + size]
        offset += size
        rows.append(
            {
                group_by: label,
                "n": int(size),
                "median": float(np.median(values)) if size else None,
                "q1": float(np.percentile(values, 25)) if size else None,
                "q3": float(np.percentile(values, 75)) if size else None,
                "mean_rank": float(group_ranks.mean()) if size else None,
            }
        )
    return pd.DataFrame(rows)


def assumptions(*checks: Assumption) -> list[dict[str, Any]]:
    return [check.to_dict() for check in checks]


def significant(p_value: float) -> bool | None:
    return None if not math.isfinite(p_value) else bool(p_value < ALPHA)
