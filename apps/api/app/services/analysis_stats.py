"""Effect sizes, confidence intervals, and assumption checks.

Tier 3 of the analysis pipeline reports inferential tests, and a p-value on its
own is the least informative number a test produces. Anything that ships from
:mod:`app.services.analysis_inference` carries four things beside the statistic:

* an **effect size**, because significance is a statement about sample size as
  much as about the world;
* a **confidence interval**, because a range is honest where a point estimate is
  not;
* **assumption checks**, because a t-test on wildly unequal variances or a
  chi-square on expected counts below five is a number without a meaning; and
* **n**, so the denominator is never implied.

These helpers are deliberately free of pandas and of the operation registry —
they take arrays and return dictionaries, so they can be read and checked as
plain statistics rather than as pipeline plumbing.

Magnitude labels ("small", "large") follow Cohen's conventional benchmarks.
They are conventions, not measurements, and every rendered label says so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from scipy import stats

# The significance threshold used for the reported ``significant_at_0.05`` flag
# and for assumption verdicts. Fixed rather than configurable: a tool that lets
# the alpha move after seeing the p-value is a p-hacking machine.
ALPHA = 0.05
CONFIDENCE_LEVEL = 0.95

# Shapiro-Wilk is defined for 3 <= n <= 5000; beyond that scipy's p-value is
# unreliable and D'Agostino's K-squared is used instead.
SHAPIRO_MAX_N = 5000
SHAPIRO_MIN_N = 3
DAGOSTINO_MIN_N = 20

# Above this many observations per group, the central limit theorem makes the
# t-test and ANOVA robust to non-normal data, so a failed normality test is
# reported as a caveat rather than a blocker.
CLT_SAFE_N = 30

# Chi-square's asymptotic distribution needs adequately populated cells. The
# conventional rule is that every expected count should be at least 5.
MIN_EXPECTED_COUNT = 5.0

MagnitudeScale = Literal["cohen_d", "correlation", "variance_explained"]

# Cohen's conventional cutoffs, per family of effect size.
_MAGNITUDE_CUTOFFS: dict[str, tuple[tuple[float, str], ...]] = {
    # d, Hedges' g, Cohen's h — standardized mean/proportion differences.
    "cohen_d": ((0.2, "negligible"), (0.5, "small"), (0.8, "medium")),
    # r, rank-biserial, Cramér's V, Cohen's w — correlation-like, on [0, 1].
    "correlation": ((0.1, "negligible"), (0.3, "small"), (0.5, "medium")),
    # eta squared, omega squared, rank-based eta squared — proportion of
    # variance. These are Cohen's eta squared cutoffs; a measure on a
    # different scale does not belong on them.
    "variance_explained": ((0.01, "negligible"), (0.06, "small"), (0.14, "medium")),
}


def magnitude(value: float | None, scale: MagnitudeScale) -> str | None:
    """Label an effect size against Cohen's conventional benchmarks."""
    if value is None or not math.isfinite(value):
        return None
    size = abs(value)
    for cutoff, label in _MAGNITUDE_CUTOFFS[scale]:
        if size < cutoff:
            return label
    return "large"


def effect_size(
    name: str, value: float | None, scale: MagnitudeScale, **extra: Any
) -> dict[str, Any]:
    """Package an effect size with its conventional magnitude label."""
    return {
        "name": name,
        "value": _finite(value),
        "magnitude": magnitude(value, scale),
        "benchmark": "Cohen's conventional cutoffs; a convention, not a measurement",
        **{key: _finite(item) if isinstance(item, float) else item for key, item in extra.items()},
    }


# Below this magnitude, rounding to a fixed number of decimal places destroys
# significant digits, so significant figures are used instead. Chosen so that
# every value at or above it keeps at least four significant digits under
# six-decimal rounding, and nothing above it changes.
_SIGNIFICANT_FIGURE_THRESHOLD = 1e-4


def json_safe(value: Any, places: int = 6) -> float | None:
    """Round a statistic to a JSON-safe value.

    Two failure modes to avoid. Non-finite statistics — a t-test between two
    zero-variance groups returns NaN — are not valid JSON, so they become None
    and the narrator can say the value could not be computed. And a p-value of
    3e-07 rounded to six decimal places is 0.0, which reads as "impossible"
    rather than "vanishingly small" — p = 0 is a claim no test can support, and
    even 8e-07 rounded to 1e-06 has thrown away most of the number. Values
    below :data:`_SIGNIFICANT_FIGURE_THRESHOLD` therefore keep significant
    figures rather than decimal places.
    """
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    if 0 < abs(as_float) < _SIGNIFICANT_FIGURE_THRESHOLD:
        return float(f"{as_float:.{places}g}")
    return round(as_float, places)


def _finite(value: Any) -> Any:
    """JSON-safe rounding that passes non-numeric values through unchanged."""
    if value is None:
        return None
    try:
        float(value)
    except (TypeError, ValueError):
        return value
    return json_safe(value)


# ---------------------------------------------------------------------------
# Assumption checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assumption:
    """One checked precondition of a statistical test.

    ``passed`` is deliberately three-valued: None means the check could not be
    evaluated (too few observations, no variance), which is different from a
    check that ran and failed.
    """

    name: str
    passed: bool | None
    detail: str
    statistic: float | None = None
    p_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "statistic": _finite(self.statistic),
            "p_value": _finite(self.p_value),
        }


def check_normality(
    values: Sequence[float], *, label: str, robust_n: int = CLT_SAFE_N
) -> Assumption:
    """Test whether *values* are plausibly normal, in the way that matters here.

    A failed normality test on a large sample is usually irrelevant — the
    central limit theorem covers the mean — while a failed test on n = 8 is a
    reason to prefer a rank-based alternative. The verdict reflects that
    distinction rather than reporting the p-value alone.
    """
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    n = int(array.size)

    if n < SHAPIRO_MIN_N:
        return Assumption(f"Normality of {label}", None, f"only {n} observation(s); not testable")
    if float(np.std(array)) == 0.0:
        return Assumption(f"Normality of {label}", None, f"{label} has no variance; not testable")

    if n <= SHAPIRO_MAX_N:
        test_name, result = "Shapiro-Wilk", stats.shapiro(array)
    elif n >= DAGOSTINO_MIN_N:
        test_name, result = "D'Agostino K²", stats.normaltest(array)
    else:  # pragma: no cover - unreachable (n > 5000 implies n >= 20)
        return Assumption(f"Normality of {label}", None, "sample size outside tested range")

    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    passed = p_value >= ALPHA

    if passed:
        detail = f"{test_name} p = {p_value:.4g}; consistent with normality (n = {n})"
    elif n >= robust_n:
        detail = (
            f"{test_name} p = {p_value:.4g}; departs from normality, but n = {n} "
            f"so the test of means is robust to it"
        )
    else:
        detail = (
            f"{test_name} p = {p_value:.4g}; departs from normality at n = {n}. "
            f"Consider a rank-based test."
        )
    return Assumption(f"Normality of {label}", passed, detail, statistic, p_value)


def check_equal_variance(groups: Sequence[Sequence[float]], *, labels: Sequence[str]) -> Assumption:
    """Brown-Forsythe (Levene, centered on the median) test for equal spread."""
    # Labels are filtered alongside the groups. Filtering only the groups and
    # then zipping against the full label list prints each surviving group's
    # spread under the previous group's name, and never shows the last one —
    # a confidently wrong detail string.
    tested = [
        (label, np.asarray(g, dtype=float))
        for label, g in zip(labels, groups, strict=True)
        if len(g) > 1
    ]
    dropped = [label for label, g in zip(labels, groups, strict=True) if len(g) <= 1]
    usable = [g for _, g in tested]
    name = "Equal variance across groups"
    if len(usable) < 2:
        return Assumption(name, None, "fewer than two groups with more than one observation")
    if all(float(np.std(g)) == 0.0 for g in usable):
        return Assumption(name, None, "every group has zero variance; not testable")

    statistic, p_value = stats.levene(*usable, center="median")
    if not math.isfinite(p_value):
        return Assumption(name, None, "Levene's test could not be computed")

    spreads = ", ".join(f"{label} sd = {np.std(g, ddof=1):.4g}" for label, g in tested)
    if dropped:
        spreads += (
            f"; {len(dropped)} group(s) ({', '.join(dropped)}) hold a single observation "
            f"and are not in this test"
        )
    passed = bool(p_value >= ALPHA)
    detail = (
        f"Levene's test p = {p_value:.4g}; "
        + ("spreads are comparable" if passed else "spreads differ materially")
        + f" ({spreads})"
    )
    return Assumption(name, passed, detail, float(statistic), float(p_value))


def check_group_sizes(sizes: dict[str, int], *, minimum: int = 5) -> Assumption:
    """Flag groups too small to support the test being run."""
    name = "Group sizes"
    if not sizes:
        return Assumption(name, None, "no groups")
    smallest_label = min(sizes, key=lambda key: sizes[key])
    smallest = sizes[smallest_label]
    passed = smallest >= minimum
    detail = f"smallest group is {smallest_label!r} at n = {smallest}" + (
        "" if passed else f"; below {minimum}, so this result is fragile"
    )
    return Assumption(name, passed, detail, float(smallest))


def check_expected_counts(expected: np.ndarray) -> Assumption:
    """Chi-square is asymptotic; it needs every expected cell adequately filled."""
    name = "Expected cell counts"
    flat = np.asarray(expected, dtype=float).ravel()
    if flat.size == 0:
        return Assumption(name, None, "no cells")
    smallest = float(flat.min())
    below = int((flat < MIN_EXPECTED_COUNT).sum())
    passed = below == 0
    detail = (
        f"smallest expected count is {smallest:.4g}"
        if passed
        else (
            f"{below} of {flat.size} cells have an expected count below "
            f"{MIN_EXPECTED_COUNT:.0f} (smallest {smallest:.4g}); the chi-square "
            f"approximation is unreliable here"
        )
    )
    return Assumption(name, passed, detail, smallest)


def check_paired_completeness(n_pairs: int, n_dropped: int, n_tied: int = 0) -> Assumption:
    """A paired test silently discards pairs; say how many, and which kind.

    Reported as "not evaluated" rather than failed when pairs were dropped:
    dropping them is correct behaviour, and whether it biases the estimate
    depends on whether the missingness is random — which is not something this
    check can determine. Calling it a failure would have the narrator report
    routine missingness as undermining the result.

    Two different discards are counted separately. ``n_dropped`` is pairs the
    *frame* lost to missing values. ``n_tied`` is pairs the *test* discarded:
    the signed-rank test ranks only non-zero differences, so "all 12 pairs
    complete" would describe 12 pairs of which it ranked 4. ``n_pairs`` is
    always the count the test actually used.
    """
    name = "Complete pairs"
    if n_dropped == 0 and n_tied == 0:
        return Assumption(name, True, f"all {n_pairs} pairs complete", float(n_pairs))

    reasons = []
    if n_dropped:
        reasons.append(
            f"{n_dropped} incomplete pair(s) were dropped, which biases the result only "
            f"if those rows are missing for a reason related to the outcome"
        )
    if n_tied:
        reasons.append(
            f"{n_tied} pair(s) with a zero difference were dropped by the test itself, "
            f"which ranks only non-zero differences"
        )
    return Assumption(
        name,
        None,
        f"the test used {n_pairs} pair(s): " + "; ".join(reasons),
        float(n_pairs),
    )


# ---------------------------------------------------------------------------
# Effect sizes
# ---------------------------------------------------------------------------


def cohens_d_independent(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Standardized mean difference between two groups, and Hedges' g.

    Returns ``(d, g)``. Hedges' g applies the small-sample correction that d
    lacks; below about n = 20 total, d is biased upward and g is the one to
    report.
    """
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n1, n2 = x.size, y.size
    if n1 < 2 or n2 < 2:
        return math.nan, math.nan
    pooled_var = ((n1 - 1) * x.var(ddof=1) + (n2 - 1) * y.var(ddof=1)) / (n1 + n2 - 2)
    if pooled_var <= 0:
        return math.nan, math.nan
    d = float((x.mean() - y.mean()) / math.sqrt(pooled_var))
    correction = 1 - 3 / (4 * (n1 + n2) - 9)
    return d, d * correction


def cohens_d_one_sample(values: Sequence[float], mu: float) -> float:
    """Standardized distance of a sample mean from a hypothesized value."""
    array = np.asarray(values, dtype=float)
    sd = float(array.std(ddof=1)) if array.size > 1 else 0.0
    if sd <= 0:
        return math.nan
    return float((array.mean() - mu) / sd)


def cohens_h(p1: float, p2: float) -> float:
    """Effect size for the difference between two proportions (arcsine scale)."""
    if not (0.0 <= p1 <= 1.0 and 0.0 <= p2 <= 1.0):
        return math.nan
    return float(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


def cramers_v(chi2: float, n: int, rows: int, columns: int) -> float:
    """Association strength for a contingency table, on [0, 1].

    Computed from the *uncorrected* chi-square by convention; the continuity
    correction exists to fix the p-value, not the effect size.
    """
    smaller = min(rows - 1, columns - 1)
    if n <= 0 or smaller <= 0 or not math.isfinite(chi2):
        return math.nan
    return float(math.sqrt(chi2 / (n * smaller)))


def cohens_w(chi2: float, n: int) -> float:
    """Effect size for a goodness-of-fit test."""
    if n <= 0 or not math.isfinite(chi2):
        return math.nan
    return float(math.sqrt(chi2 / n))


def eta_squared(ss_between: float, ss_total: float) -> float:
    """Proportion of variance in the outcome attributable to group membership."""
    if ss_total <= 0:
        return math.nan
    return float(ss_between / ss_total)


def omega_squared(ss_between: float, ss_total: float, df_between: int, ms_within: float) -> float:
    """Less biased sibling of eta squared; can go negative for null effects."""
    denominator = ss_total + ms_within
    if denominator <= 0:
        return math.nan
    return float((ss_between - df_between * ms_within) / denominator)


def eta_squared_rank(h: float, k: int, n: int) -> float:
    """Rank-based eta squared for Kruskal-Wallis: ``(H - k + 1) / (n - k)``.

    Named for what it computes. This is Cohen's eta squared on ranks, not the
    textbook epsilon squared, which is ``H / (n - 1)`` — a different number.
    On H = 7.5358 with n = 41 and k = 3 they are 0.1457 and 0.1884, a 29% gap
    that straddles the 0.14 "large" cutoff.

    Both are legitimate; this one is kept because it is what the pipeline has
    always reported and it is what the ``variance_explained`` benchmarks
    (0.01 / 0.06 / 0.14, Cohen's eta squared cutoffs) belong to. Only the label
    was wrong.
    """
    if n <= k or not math.isfinite(h):
        return math.nan
    return float((h - k + 1) / (n - k))


def rank_biserial_mann_whitney(u1: float, n1: int, n2: int) -> float:
    """Rank-biserial correlation on [-1, 1] from the Mann-Whitney U.

    Signed so that a negative value means the *first* group ranks lower, which
    matches the sign of the reported median difference. Some texts use the
    opposite sign; the direction is stated in the result rather than assumed.
    """
    if n1 <= 0 or n2 <= 0:
        return math.nan
    return float(2 * u1 / (n1 * n2) - 1)


def rank_biserial_wilcoxon(differences: Sequence[float]) -> float:
    """Matched-pairs rank-biserial: the rank-weighted balance of signs."""
    diffs = np.asarray(differences, dtype=float)
    diffs = diffs[np.isfinite(diffs) & (diffs != 0)]
    if diffs.size == 0:
        return math.nan
    ranks = stats.rankdata(np.abs(diffs))
    total = ranks.sum()
    if total <= 0:
        return math.nan
    positive = ranks[diffs > 0].sum()
    negative = ranks[diffs < 0].sum()
    return float((positive - negative) / total)


# ---------------------------------------------------------------------------
# Confidence intervals
# ---------------------------------------------------------------------------


def interval(low: float | None, high: float | None, **extra: Any) -> dict[str, Any]:
    """Package a confidence interval with its level."""
    return {"low": _finite(low), "high": _finite(high), "level": CONFIDENCE_LEVEL, **extra}


def mean_ci(values: Sequence[float]) -> tuple[float, float]:
    """Two-sided t interval for a sample mean."""
    array = np.asarray(values, dtype=float)
    n = array.size
    if n < 2:
        return math.nan, math.nan
    sd = float(array.std(ddof=1))
    if sd <= 0:
        mean = float(array.mean())
        return mean, mean
    margin = float(stats.t.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2, n - 1)) * sd / math.sqrt(n)
    mean = float(array.mean())
    return mean - margin, mean + margin


def mean_difference_ci(
    a: Sequence[float], b: Sequence[float], *, equal_var: bool
) -> tuple[float, float]:
    """Interval for the difference in means, matching the t-test that was run.

    Welch's interval uses the Welch-Satterthwaite degrees of freedom, so the
    interval and the p-value describe the same test rather than two different
    ones.
    """
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n1, n2 = x.size, y.size
    if n1 < 2 or n2 < 2:
        return math.nan, math.nan

    var1, var2 = x.var(ddof=1), y.var(ddof=1)
    if equal_var:
        pooled = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        standard_error = math.sqrt(pooled * (1 / n1 + 1 / n2))
        dof: float = n1 + n2 - 2
    else:
        standard_error = math.sqrt(var1 / n1 + var2 / n2)
        dof = welch_dof(var1, n1, var2, n2)

    if standard_error <= 0 or not math.isfinite(dof) or dof <= 0:
        return math.nan, math.nan
    difference = float(x.mean() - y.mean())
    margin = float(stats.t.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2, dof)) * standard_error
    return difference - margin, difference + margin


def welch_dof(var1: float, n1: int, var2: float, n2: int) -> float:
    """Welch-Satterthwaite degrees of freedom."""
    if n1 < 2 or n2 < 2:
        return math.nan
    numerator = (var1 / n1 + var2 / n2) ** 2
    denominator = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
    if denominator <= 0:
        return math.nan
    return float(numerator / denominator)


def wilson_ci(successes: int, n: int) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Preferred over the normal approximation, which produces intervals extending
    past 0 or 1 and collapses to zero width at p = 0 or p = 1 — exactly the
    cases where a survey tool most needs an honest interval.
    """
    if n <= 0:
        return math.nan, math.nan
    z = float(stats.norm.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2))
    p = successes / n
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    margin = (z / denominator) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return max(0.0, center - margin), min(1.0, center + margin)


def proportion_difference_ci(
    successes1: int, n1: int, successes2: int, n2: int
) -> tuple[float, float]:
    """Newcombe's interval for a difference in proportions.

    Built from the two Wilson intervals rather than from a pooled normal
    approximation, so it stays sensible with small counts.
    """
    if n1 <= 0 or n2 <= 0:
        return math.nan, math.nan
    low1, high1 = wilson_ci(successes1, n1)
    low2, high2 = wilson_ci(successes2, n2)
    p1, p2 = successes1 / n1, successes2 / n2
    difference = p1 - p2
    lower = difference - math.sqrt((p1 - low1) ** 2 + (high2 - p2) ** 2)
    upper = difference + math.sqrt((high1 - p1) ** 2 + (p2 - low2) ** 2)
    return max(-1.0, lower), min(1.0, upper)


# ---------------------------------------------------------------------------
# Multiple comparisons
# ---------------------------------------------------------------------------


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """False-discovery-rate adjusted p-values, in the order given.

    Asking several questions of one dataset and reporting each at alpha = 0.05
    is how a chat interface manufactures a false positive: at five independent
    tests the chance of at least one spurious "significant" result is about one
    in four. The step-up procedure adjusts for how many tests were actually run.

    ``None`` entries pass through unchanged and are excluded from the count, so
    a test that could not be computed does not inflate the correction.
    """
    indexed = [
        (index, float(value))
        for index, value in enumerate(p_values)
        if value is not None and math.isfinite(float(value))
    ]
    adjusted: list[float | None] = list(p_values)
    if not indexed:
        return adjusted

    indexed.sort(key=lambda pair: pair[1])
    m = len(indexed)
    running = 1.0
    # Walk from the largest p-value down, keeping the running minimum, so the
    # adjusted values stay monotone in the original ranking.
    for rank in range(m, 0, -1):
        index, p_value = indexed[rank - 1]
        running = min(running, p_value * m / rank)
        adjusted[index] = min(1.0, running)
    return adjusted
