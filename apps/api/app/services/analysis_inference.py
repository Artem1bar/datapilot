"""Tier 3: comparisons of means and ranks, executed over the full dataset.

Where :mod:`app.services.analysis_executor` answers "what is it", this module
answers "is the difference real". Both are step 3 of the pipeline — the model
selected the test, code runs it, and the model later explains a result it did
not produce. Count-based tests live in
:mod:`app.services.analysis_categorical`.

Every operation here returns the same four things beside its statistic: an
effect size, a confidence interval, explicit assumption checks, and n. A tool
that reports only a p-value invites the two most common mistakes in applied
statistics — reading significance as importance, and running a test whose
assumptions the data violate. The assumption checks are surfaced to the
narrator, which is required to state violations rather than bury them.

The operations refuse rather than degrade: an independent t-test over three
groups raises and names ANOVA instead of silently comparing the first two.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.oneway import anova_oneway

from app.services.analysis_prep import (
    MIN_GROUP_N,
    alternative_of,
    assumptions,
    directional_suffix,
    exclusion_note,
    group_summary,
    interval_sidedness,
    numeric_series,
    rank_summary,
    require_group_sizes,
    require_two_groups,
    significant,
    split_groups,
)
from app.services.analysis_result import ExecutionError, OperationResult, frame_to_result
from app.services.analysis_stats import (
    Assumption,
    check_equal_variance,
    check_group_sizes,
    check_normality,
    check_paired_completeness,
    cohens_d_independent,
    cohens_d_one_sample,
    effect_size,
    eta_squared,
    eta_squared_rank,
    interval,
    mean_ci,
    mean_difference_ci,
    omega_squared,
    rank_biserial_mann_whitney,
    rank_biserial_wilcoxon,
)

logger = logging.getLogger(__name__)

# Hodges-Lehmann is an all-pairs median; skip it past this many comparisons
# rather than allocating a matrix that dwarfs the dataset.
MAX_HODGES_LEHMANN_PAIRS = 4_000_000

# ---------------------------------------------------------------------------
# t-tests
# ---------------------------------------------------------------------------


def _ttest_one_sample(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column = params["column"]
    if "mu" not in params:
        raise ExecutionError("ttest: a one-sample test requires 'mu', the value to test against")
    mu = float(params["mu"])
    alternative = alternative_of(params)

    values = numeric_series(df, column).dropna().to_numpy(dtype=float)
    excluded = len(df) - values.size
    if values.size < MIN_GROUP_N:
        raise ExecutionError(f"ttest: only {values.size} non-null value(s) in {column!r}")

    result = stats.ttest_1samp(values, mu, alternative=alternative)
    low, high = mean_ci(values)
    d = cohens_d_one_sample(values, mu)

    frame = pd.DataFrame(
        [
            {
                "measure": column,
                "n": int(values.size),
                "mean": float(values.mean()),
                "sd": float(values.std(ddof=1)),
                "ci95_low": low,
                "ci95_high": high,
                "tested_against": mu,
            }
        ]
    )
    payload = {
        "test": f"One-sample t-test against {mu:g}{directional_suffix(alternative)}",
        "alternative": alternative,
        "statistic": float(result.statistic),
        "dof": int(values.size - 1),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "mean": float(values.mean()),
        "mean_difference": float(values.mean() - mu),
        "confidence_interval": interval(
            low, high, of="the sample mean", **interval_sidedness(alternative)
        ),
        "effect_size": effect_size("Cohen's d", d, "cohen_d"),
        "assumptions": assumptions(check_normality(values, label=column)),
    }
    return frame_to_result(
        frame,
        op="ttest",
        label=label,
        n=int(values.size),
        n_excluded=excluded,
        notes=exclusion_note(excluded),
        stats_payload=payload,
    )


def _ttest_independent(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column, group_by = params["column"], params["group_by"]
    alternative = alternative_of(params)
    equal_var = bool(params.get("equal_var", False))

    labels, groups, used, excluded = split_groups(df, group_by, column)
    require_two_groups(labels, "ttest")
    require_group_sizes(labels, groups, "ttest")

    first, second = groups
    result = stats.ttest_ind(first, second, equal_var=equal_var, alternative=alternative)
    low, high = mean_difference_ci(first, second, equal_var=equal_var)
    d, hedges_g = cohens_d_independent(first, second)

    test_name = (
        f"Student's t-test ({labels[0]} vs {labels[1]}, pooled variance)"
        if equal_var
        else f"Welch's t-test ({labels[0]} vs {labels[1]}, unequal variance)"
    ) + directional_suffix(alternative)
    payload = {
        "test": test_name,
        "alternative": alternative,
        "comparison": f"{labels[0]} minus {labels[1]}",
        "statistic": float(result.statistic),
        "dof": float(getattr(result, "df", np.nan)),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "mean_difference": float(first.mean() - second.mean()),
        "confidence_interval": interval(
            low,
            high,
            of=f"the difference in mean {column}",
            **interval_sidedness(alternative),
        ),
        "effect_size": effect_size("Cohen's d", d, "cohen_d", hedges_g=hedges_g),
        "assumptions": assumptions(
            check_equal_variance(groups, labels=labels),
            *(
                check_normality(values, label=f"{column} in {group_label}")
                for group_label, values in zip(labels, groups, strict=True)
            ),
            check_group_sizes(
                {
                    group_label: int(values.size)
                    for group_label, values in zip(labels, groups, strict=True)
                }
            ),
        ),
    }
    return frame_to_result(
        group_summary(labels, groups, group_by),
        op="ttest",
        label=label,
        n=used,
        n_excluded=excluded,
        notes=exclusion_note(excluded),
        stats_payload=payload,
    )


def _ttest_paired(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column, column2 = params["column"], params["column2"]
    alternative = alternative_of(params)

    frame = pd.DataFrame(
        {column: numeric_series(df, column), column2: numeric_series(df, column2)}
    ).dropna()
    excluded = len(df) - len(frame)
    if len(frame) < MIN_GROUP_N:
        raise ExecutionError(f"ttest: only {len(frame)} complete pair(s) of {column!r}/{column2!r}")

    first = frame[column].to_numpy(dtype=float)
    second = frame[column2].to_numpy(dtype=float)
    differences = first - second

    result = stats.ttest_rel(first, second, alternative=alternative)
    low, high = mean_ci(differences)
    sd = float(differences.std(ddof=1))
    d = float(differences.mean() / sd) if sd > 0 else math.nan

    summary = pd.DataFrame(
        [
            {"measure": column, "n": len(frame), "mean": float(first.mean())},
            {"measure": column2, "n": len(frame), "mean": float(second.mean())},
            {"measure": "difference", "n": len(frame), "mean": float(differences.mean())},
        ]
    )
    payload = {
        "test": f"Paired t-test ({column} minus {column2}){directional_suffix(alternative)}",
        "alternative": alternative,
        "statistic": float(result.statistic),
        "dof": int(len(frame) - 1),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "mean_difference": float(differences.mean()),
        "confidence_interval": interval(
            low, high, of="the mean paired difference", **interval_sidedness(alternative)
        ),
        "effect_size": effect_size("Cohen's d (paired)", d, "cohen_d"),
        "assumptions": assumptions(
            check_normality(differences, label="the paired differences"),
            check_paired_completeness(len(frame), excluded),
        ),
    }
    return frame_to_result(
        summary,
        op="ttest",
        label=label,
        n=len(frame),
        n_excluded=excluded,
        notes=exclusion_note(excluded),
        stats_payload=payload,
    )


_TTEST_KINDS = {
    "one_sample": _ttest_one_sample,
    "independent": _ttest_independent,
    "paired": _ttest_paired,
}


def op_ttest(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    kind = params.get("kind")
    handler = _TTEST_KINDS.get(str(kind))
    if handler is None:
        raise ExecutionError(f"ttest: unknown kind {kind!r} (allowed: {sorted(_TTEST_KINDS)})")
    for required in ("column",):
        if required not in params:
            raise ExecutionError(f"ttest: missing required parameter {required!r}")
    if kind == "independent" and "group_by" not in params:
        raise ExecutionError("ttest: an independent test requires 'group_by'")
    if kind == "paired" and "column2" not in params:
        raise ExecutionError("ttest: a paired test requires 'column2'")
    return handler(df, params, label)


# ---------------------------------------------------------------------------
# Multi-group comparisons
# ---------------------------------------------------------------------------


def _sum_of_squares(groups: list[np.ndarray]) -> tuple[float, float, float]:
    """Between, within, and total sums of squares for a one-way layout."""
    combined = np.concatenate(groups)
    grand_mean = float(combined.mean())
    ss_total = float(((combined - grand_mean) ** 2).sum())
    ss_between = float(sum(g.size * (g.mean() - grand_mean) ** 2 for g in groups))
    return ss_between, ss_total - ss_between, ss_total


def _tukey_post_hoc(labels: list[str], groups: list[np.ndarray]) -> dict[str, Any]:
    """Pairwise comparisons with the family-wise error rate controlled.

    Running every pairwise t-test after a significant ANOVA is the classic way
    to manufacture a false positive; Tukey's HSD adjusts for the number of
    comparisons being made.
    """
    result = stats.tukey_hsd(*groups)
    low, high = result.confidence_interval()
    pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            p_value = float(result.pvalue[i, j])
            pairs.append(
                {
                    "group_a": labels[i],
                    "group_b": labels[j],
                    "difference": float(result.statistic[i, j]),
                    "p_value": p_value,
                    "ci95_low": float(low[i, j]),
                    "ci95_high": float(high[i, j]),
                    "significant_at_0.05": significant(p_value),
                }
            )
    return {
        "test": "Tukey HSD (family-wise error rate controlled across all pairs)",
        "pairs": pairs,
    }


def _oneway_test(
    column: str, labels: list[str], groups: list[np.ndarray], heteroscedastic: bool
) -> dict[str, Any]:
    """The omnibus test these groups support, with the reason it was chosen.

    The classic F pools every group's variance into one error term. When the
    spreads genuinely differ and the group sizes are unequal it is
    anti-conservative — on the case this branch was written against (n =
    40/40/8, sds 2.35/2.04/20.92) the classic F reports p < 1e-5 while Welch
    reports p = 0.09, so the two disagree about whether there is an effect at
    all. Surfacing the Levene failure while still handing the narrator the
    p-value that failure invalidates is exactly the silent degradation the
    scope doc rules out, so the test itself changes rather than a caveat being
    appended to the wrong one.

    Selecting the test from the assumption check rather than from the outcome
    is the textbook rule and not a researcher degree of freedom: the spreads
    are fixed before any mean is compared.
    """
    if not heteroscedastic:
        result = stats.f_oneway(*groups)
        return {
            "test": f"One-way ANOVA of {column} across {len(labels)} groups",
            "statistic": float(result.statistic),
            "df_between": float(len(groups) - 1),
            "df_within": float(sum(values.size for values in groups) - len(groups)),
            "p_value": float(result.pvalue),
        }
    # statsmodels 0.15.0: anova_oneway(data, use_var="unequal") returns an
    # AnovaResult whose .df is (numerator, Satterthwaite-Welch denominator).
    # scipy has no Welch ANOVA.
    result = anova_oneway(tuple(groups), use_var="unequal")
    return {
        "test": f"Welch's ANOVA of {column} across {len(labels)} groups (unequal variances)",
        "test_chosen_because": (
            "Levene's test rejected equal variances across the groups, so the classic F's "
            "single pooled error term does not describe them; Welch's ANOVA weights each "
            "group by its own variance and adjusts the denominator degrees of freedom"
        ),
        "statistic": float(result.statistic),
        "df_between": float(result.df_num),
        "df_within": float(result.df_denom),
        "p_value": float(result.pvalue),
    }


def op_anova(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column, group_by = params["column"], params["group_by"]
    labels, groups, used, excluded = split_groups(df, group_by, column)
    if len(labels) < 2:
        raise ExecutionError(f"anova: needs at least two groups, found {len(labels)}")
    require_group_sizes(labels, groups, "anova")

    equal_variance = check_equal_variance(groups, labels=labels)
    # Three-valued: only an assumption that ran and failed switches the test.
    # None means it could not be evaluated, where neither test means much.
    heteroscedastic = equal_variance.passed is False
    test_block = _oneway_test(column, labels, groups, heteroscedastic)

    ss_between, ss_within, ss_total = _sum_of_squares(groups)
    df_between = len(groups) - 1
    df_within = used - len(groups)
    ms_within = ss_within / df_within if df_within > 0 else math.nan

    notes = exclusion_note(excluded)
    if len(labels) == 2:
        notes.append("With two groups, ANOVA is equivalent to a pooled-variance t-test.")
    if heteroscedastic:
        notes.append(
            "The group spreads differ materially, so the omnibus test reported here is "
            "Welch's ANOVA rather than the classic F, which is anti-conservative when the "
            "smaller groups carry the larger variances."
        )

    # eta squared is SSB/SST — a description of this sample either way. Omega
    # squared estimates a population effect from the equal-variance model, so
    # under a failed Levene it is reported with that stated rather than
    # silently dropped or silently trusted.
    effect_extras: dict[str, Any] = {
        "omega_squared": omega_squared(ss_between, ss_total, df_between, ms_within)
    }
    if heteroscedastic:
        effect_extras["caveat"] = (
            "both figures come from the equal-variance sum-of-squares decomposition; "
            "with unequal spreads read eta squared as descriptive of this sample and "
            "omega squared as approximate"
        )

    payload: dict[str, Any] = {
        **test_block,
        "significant_at_0.05": significant(float(test_block["p_value"])),
        "effect_size": effect_size(
            "eta squared",
            eta_squared(ss_between, ss_total),
            "variance_explained",
            **effect_extras,
        ),
        "assumptions": assumptions(
            equal_variance,
            *(
                check_normality(values, label=f"{column} in {group_label}")
                for group_label, values in zip(labels, groups, strict=True)
            ),
            check_group_sizes(
                {
                    group_label: int(values.size)
                    for group_label, values in zip(labels, groups, strict=True)
                }
            ),
        ),
    }
    # Tukey builds every pairwise p-value from the same pooled error term the
    # omnibus F just abandoned. On the measured case it declares two pairs
    # significant at p < 1e-5 beside a Welch omnibus of p = 0.09. A caveat is
    # not enough — a reader anchors on the number, and we have just declined to
    # show the omnibus F for this exact reason. Games-Howell is the procedure
    # that applies under unequal variances and is in neither scipy nor
    # statsmodels, so it is named rather than hand-rolled here.
    if heteroscedastic:
        payload["post_hoc"] = {
            "test": "not computed",
            "reason": (
                "Tukey HSD assumes one common variance across groups, which Levene's test "
                "rejected here, so its pairwise p-values would rest on the assumption the "
                "omnibus test just abandoned. Games-Howell is the post-hoc that applies "
                "under unequal variances."
            ),
        }
    elif len(labels) > 1:
        try:
            payload["post_hoc"] = _tukey_post_hoc(labels, groups)
        except Exception as exc:  # scipy raising on a degenerate layout
            logger.info("anova: Tukey HSD not computed (%s)", exc)

    return frame_to_result(
        group_summary(labels, groups, group_by),
        op="anova",
        label=label,
        n=used,
        n_excluded=excluded,
        notes=notes,
        stats_payload=payload,
    )


def op_kruskal(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column, group_by = params["column"], params["group_by"]
    labels, groups, used, excluded = split_groups(df, group_by, column)
    if len(labels) < 2:
        raise ExecutionError(f"kruskal: needs at least two groups, found {len(labels)}")
    require_group_sizes(labels, groups, "kruskal")

    result = stats.kruskal(*groups)
    h = float(result.statistic)
    payload = {
        "test": f"Kruskal-Wallis test of {column} across {len(labels)} groups",
        "statistic": h,
        "dof": int(len(labels) - 1),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "effect_size": effect_size(
            # Named for the formula it uses. Textbook epsilon squared is
            # H / (n - 1) — a different number, and around the 0.06 and 0.14
            # cutoffs a different magnitude word.
            "eta squared (rank-based)",
            eta_squared_rank(h, len(labels), used),
            "variance_explained",
            definition="(H - k + 1) / (n - k), Cohen's eta squared computed on ranks",
        ),
        "assumptions": assumptions(
            check_group_sizes(
                {
                    group_label: int(values.size)
                    for group_label, values in zip(labels, groups, strict=True)
                }
            ),
            Assumption(
                "Comparable distribution shapes",
                None,
                "Kruskal-Wallis makes no normality assumption, but reads as a test of "
                "medians only when the groups have similar shapes; otherwise it tests "
                "stochastic dominance",
            ),
        ),
    }
    return frame_to_result(
        rank_summary(labels, groups, group_by),
        op="kruskal",
        label=label,
        n=used,
        n_excluded=excluded,
        notes=exclusion_note(excluded)
        + ["Rank-based: robust to outliers and to non-normal distributions."],
        stats_payload=payload,
    )


def _hodges_lehmann(first: np.ndarray, second: np.ndarray) -> float:
    """Median of all pairwise differences — the shift a rank test estimates."""
    if first.size * second.size > MAX_HODGES_LEHMANN_PAIRS:
        return math.nan
    return float(np.median(first[:, None] - second[None, :]))


def op_mannwhitney(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column, group_by = params["column"], params["group_by"]
    alternative = alternative_of(params)
    labels, groups, used, excluded = split_groups(df, group_by, column)
    require_two_groups(labels, "mannwhitney")
    require_group_sizes(labels, groups, "mannwhitney")

    first, second = groups
    result = stats.mannwhitneyu(first, second, alternative=alternative)
    r = rank_biserial_mann_whitney(float(result.statistic), first.size, second.size)

    payload = {
        "test": (
            f"Mann-Whitney U test ({labels[0]} vs {labels[1]}){directional_suffix(alternative)}"
        ),
        "alternative": alternative,
        "comparison": f"{labels[0]} minus {labels[1]}",
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "median_difference": float(np.median(first) - np.median(second)),
        "hodges_lehmann_shift": _hodges_lehmann(first, second),
        "effect_size": effect_size(
            "rank-biserial correlation",
            r,
            "correlation",
            direction=f"negative means {labels[0]} ranks below {labels[1]}",
        ),
        "assumptions": assumptions(
            check_group_sizes(
                {
                    group_label: int(values.size)
                    for group_label, values in zip(labels, groups, strict=True)
                }
            ),
            Assumption(
                "Comparable distribution shapes",
                None,
                "reads as a comparison of medians only when the two groups have similar "
                "shapes; otherwise it tests whether one group tends to rank above the other",
            ),
        ),
    }
    return frame_to_result(
        rank_summary(labels, groups, group_by),
        op="mannwhitney",
        label=label,
        n=used,
        n_excluded=excluded,
        notes=exclusion_note(excluded)
        + ["Rank-based: robust to outliers and to non-normal distributions."],
        stats_payload=payload,
    )


def op_wilcoxon(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column, column2 = params["column"], params["column2"]
    alternative = alternative_of(params)

    frame = pd.DataFrame(
        {column: numeric_series(df, column), column2: numeric_series(df, column2)}
    ).dropna()
    excluded = len(df) - len(frame)
    if len(frame) < MIN_GROUP_N:
        raise ExecutionError(
            f"wilcoxon: only {len(frame)} complete pair(s) of {column!r}/{column2!r}"
        )

    first = frame[column].to_numpy(dtype=float)
    second = frame[column2].to_numpy(dtype=float)
    differences = first - second
    zero_differences = int((differences == 0).sum())
    if np.count_nonzero(differences) == 0:
        raise ExecutionError("wilcoxon: every pair is identical, so there is nothing to test")

    result = stats.wilcoxon(first, second, alternative=alternative)
    r = rank_biserial_wilcoxon(differences)

    summary = pd.DataFrame(
        [
            {"measure": column, "n": len(frame), "median": float(np.median(first))},
            {"measure": column2, "n": len(frame), "median": float(np.median(second))},
            {"measure": "difference", "n": len(frame), "median": float(np.median(differences))},
        ]
    )
    # scipy's default zero_method="wilcox" discards tied pairs before ranking,
    # so the pairs the test saw and the pairs it was handed are two different
    # counts. Both are reported, each named, rather than one standing in for
    # the other: n_pairs is what was ranked, n_complete_pairs is what survived
    # the dropna, and n is the former because that is the statistic's own
    # denominator.
    ranked_pairs = int(np.count_nonzero(differences))
    notes = exclusion_note(excluded) + [
        "Rank-based: robust to outliers and to non-normal differences."
    ]
    if zero_differences:
        notes.append(
            f"{zero_differences} of {len(frame)} pair(s) had a zero difference and were "
            f"dropped by the test, which ranked {ranked_pairs}."
        )

    payload = {
        "test": (
            f"Wilcoxon signed-rank test ({column} vs {column2}){directional_suffix(alternative)}"
        ),
        "alternative": alternative,
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "significant_at_0.05": significant(float(result.pvalue)),
        "n_pairs": ranked_pairs,
        "n_complete_pairs": int(len(frame)),
        "n_tied_pairs": zero_differences,
        "median_difference": float(np.median(differences)),
        # The median is over every complete pair and the effect size over the
        # ranked ones. With many ties they disagree by construction — a median
        # of 0 beside a rank-biserial of 1 — so each names its own set instead
        # of being silently read as describing the other's.
        "median_difference_over": f"all {len(frame)} complete pair(s), ties included",
        "effect_size": effect_size(
            "matched-pairs rank-biserial",
            r,
            "correlation",
            computed_over=(
                f"the {ranked_pairs} pair(s) with a non-zero difference — the pairs the "
                f"signed-rank test ranks"
            ),
        ),
        "assumptions": assumptions(
            check_paired_completeness(ranked_pairs, excluded, zero_differences)
        ),
    }
    return frame_to_result(
        summary,
        op="wilcoxon",
        label=label,
        n=ranked_pairs,
        n_excluded=len(df) - ranked_pairs,
        notes=notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _normality_row(values: np.ndarray, group_label: str) -> dict[str, Any]:
    check = check_normality(values, label=group_label)
    return {
        "group": group_label,
        "n": int(values.size),
        "mean": float(values.mean()) if values.size else None,
        "sd": float(values.std(ddof=1)) if values.size > 1 else None,
        "skewness": float(stats.skew(values, bias=False)) if values.size > 2 else None,
        "kurtosis": float(stats.kurtosis(values, bias=False)) if values.size > 3 else None,
        "shapiro_p": check.p_value,
        "normal_at_0.05": check.passed,
        "verdict": check.detail,
    }


def op_normality_test(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """Whether a column is plausibly normal — the check behind test selection.

    Exposed as its own operation so "can I use a t-test here?" is answerable
    directly, rather than only as a footnote on some other test's output.
    """
    column = params["column"]
    group_by = params.get("group_by")

    series = numeric_series(df, column).dropna()
    excluded = len(df) - len(series)
    if len(series) < 3:
        raise ExecutionError(
            f"normality_test: only {len(series)} non-null value(s) in {column!r}; need at least 3"
        )

    overall = _normality_row(series.to_numpy(dtype=float), "(all rows)")
    if group_by is not None:
        labels, groups, used, group_excluded = split_groups(df, group_by, column)
        rows = [
            _normality_row(values, group_label)
            for group_label, values in zip(labels, groups, strict=True)
            if values.size >= 3
        ]
        if not rows:
            raise ExecutionError(
                f"normality_test: no group in {group_by!r} has at least 3 values of {column!r}"
            )
        frame = pd.DataFrame(rows).rename(columns={"group": group_by})
        n, excluded = used, group_excluded
    else:
        frame = pd.DataFrame([overall])
        n = len(series)

    payload = {
        "test": "Shapiro-Wilk (D'Agostino K² above 5,000 rows)",
        "overall": overall,
        "assumptions": assumptions(
            Assumption(
                "Interpretation",
                None,
                "a significant result means the data depart from normality; with more than "
                "30 observations per group, tests of means are robust to that departure",
            )
        ),
    }
    return frame_to_result(
        frame,
        op="normality_test",
        label=label,
        n=n,
        n_excluded=excluded,
        notes=exclusion_note(excluded),
        stats_payload=payload,
    )


# Registered into the executor's dispatch table.


# Registered into the executor's dispatch table.
INFERENCE_OPERATIONS = {
    "ttest": op_ttest,
    "anova": op_anova,
    "kruskal": op_kruskal,
    "mannwhitney": op_mannwhitney,
    "wilcoxon": op_wilcoxon,
    "normality_test": op_normality_test,
}
