"""Reading a scatter plot: interpretation help, built from the numbers.

A chart and a p-value are not an interpretation. This module turns the
statistics a scatter operation computed into the sentences a careful analyst
would say next to the plot: which way the association runs and how strong it
is, what the slope means in the data's own units, whether the slope is
distinguishable from zero, and the caveats that apply to *this* plot — a
small sample, excluded rows, a pooled line over several groups. It ends with
questions the chat can answer, so the reading leads somewhere.

Every sentence is assembled from computed values. Nothing here is generated
by a model, and no figure appears that was not measured.
"""

from __future__ import annotations

import math
from typing import Any

from app.services.analysis_result import OperationResult

# Conventional bands for the size of a correlation, on |r|: Cohen (1988)
# calls 0.1 small, 0.3 medium and 0.5 large. Below 0.1 the association is
# negligible. Conventions, not laws — the summary names them as such.
STRENGTH_BANDS: tuple[tuple[float, str], ...] = (
    (0.1, "negligible"),
    (0.3, "weak"),
    (0.5, "moderate"),
)
STRONG = "strong"

# The conventional level for "distinguishable from zero".
SIGNIFICANCE_LEVEL = 0.05

# Below this many rows a slope and its p-value move with a handful of points.
SMALL_SAMPLE = 30

# Enough to lead somewhere; not a syllabus.
MAX_NEXT_STEPS = 3


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def strength_of(r: Any) -> str | None:
    """The conventional name for a correlation of this size, or None if unknown."""
    value = _finite(r)
    if value is None:
        return None
    magnitude = abs(value)
    for bound, name in STRENGTH_BANDS:
        if magnitude < bound:
            return name
    return STRONG


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _summary(
    x: str, y: str, n: int, r: float, slope: float, r_squared: float | None, p: float | None
) -> tuple[list[str], str, str, bool | None]:
    """The reading itself; returns the sentences, the direction, strength and significance."""
    strength = strength_of(r) or "negligible"
    direction = "none" if strength == "negligible" else ("positive" if r > 0 else "negative")
    significant = p < SIGNIFICANCE_LEVEL if p is not None else None

    sentences: list[str] = []
    if strength == "negligible":
        sentences.append(
            f"There is no meaningful linear relationship between {x} and {y} "
            f"in this data (r = {r:.2f})."
        )
    else:
        goes_with = "higher" if r > 0 else "lower"
        sentences.append(
            f"A {strength} {direction} linear association: higher {x} goes with "
            f"{goes_with} {y} (r = {r:.2f})."
        )
        if significant:
            more_or_less = "more" if slope > 0 else "less"
            sentences.append(
                f"On average, each additional unit of {x} is associated with "
                f"{abs(slope):.4g} {more_or_less} {y}."
            )
    if r_squared is not None:
        sentences.append(
            f"A straight line in {x} accounts for {r_squared * 100:.0f}% of the variation "
            f"in {y}; the rest is not explained by that line."
        )
    if p is not None:
        if significant:
            sentences.append(
                f"The slope is distinguishable from zero at the conventional "
                f"{SIGNIFICANCE_LEVEL:.0%} level (p = {p:.2g}, n = {n:,})."
            )
        else:
            sentences.append(
                f"The data do not distinguish the slope from zero at the "
                f"{SIGNIFICANCE_LEVEL:.0%} level (p = {p:.2g}, n = {n:,}): a real "
                "relationship may be too small to detect at this sample size, or there "
                "may be none."
            )
    return sentences, direction, strength, significant


def _caveats(result: OperationResult) -> list[str]:
    plot = result.plot
    caveats = [
        "Association is not causation: a third factor could drive both, or the "
        "direction could run the other way.",
        "A straight line is a summary. Curvature, clusters or a few extreme points "
        "can produce the same r; look at the plot, not only the number.",
    ]
    if result.n < SMALL_SAMPLE:
        caveats.append(
            f"With n = {result.n}, the estimates are unstable; a handful of points can "
            "move the line and the p-value."
        )
    if result.n_excluded:
        verb = "was" if result.n_excluded == 1 else "were"
        caveats.append(
            f"{_plural(result.n_excluded, 'row')} {verb} excluded for missing values; if "
            "they differ systematically from the rest, the fit is biased."
        )
    if plot is not None and plot.sampled:
        caveats.append(
            "Only a sample of points is drawn; the line and the statistics use every complete row."
        )
    if plot is not None and plot.group:
        caveats.append(
            f"The line pools all {len(plot.groups)} groups of {plot.group}; the "
            "relationship inside each group can differ from the pooled one, or even "
            "reverse (Simpson's paradox)."
        )
    if plot is not None and plot.size:
        caveats.append(
            f"Bubble area shows {plot.size}; the line ignores it. Large bubbles draw the "
            "eye but carry no extra weight in the fit."
        )
    return caveats


def _next_steps(
    result: OperationResult, x: str, y: str, strength: str | None, significant: bool | None
) -> list[dict[str, str]]:
    plot = result.plot
    steps: list[dict[str, str]] = []
    if plot is not None and plot.group:
        steps.append(
            {
                "question": f"Does the relationship between {y} and {x} differ across {plot.group}?",
                "why": "Fits the line within each group, to check the pooled pattern holds "
                "inside them.",
            }
        )
    if plot is not None and plot.size:
        steps.append(
            {
                "question": f"Is {plot.size} related to {y} as well?",
                "why": "The bubble sizes may carry part of the pattern you are seeing.",
            }
        )
    steps.append(
        {
            "question": f"What is the Spearman correlation between {x} and {y}?",
            "why": "Rank-based, so a few extreme points cannot dominate the way they can "
            "in Pearson's r.",
        }
    )
    if significant and strength not in (None, "negligible"):
        steps.append(
            {
                "question": f"Which other columns predict {y} alongside {x}?",
                "why": f"A regression with more predictors shows whether {x} still matters "
                "once they are accounted for.",
            }
        )
    return steps[:MAX_NEXT_STEPS]


def interpret_scatter(result: OperationResult) -> dict[str, Any]:
    """Read one scatter result: direction, strength, significance, caveats, next steps."""
    plot = result.plot
    x = plot.x if plot is not None else str(result.columns[0])
    y = plot.y if plot is not None else str(result.columns[1])
    stats = result.stats
    r, slope = _finite(stats.get("r")), _finite(stats.get("slope"))
    r_squared, p = _finite(stats.get("r_squared")), _finite(stats.get("p_value"))

    if r is None or slope is None:
        summary = [
            f"The fit could not be computed: {x} may be constant, or the rows too few "
            "to fit a line through."
        ]
        direction, strength, significant = "none", None, None
    else:
        summary, direction, strength, significant = _summary(x, y, result.n, r, slope, r_squared, p)

    return {
        "direction": direction,
        "strength": strength,
        "significant": significant,
        "summary": summary,
        "caveats": _caveats(result),
        "next_steps": _next_steps(result, x, y, strength, significant),
    }
