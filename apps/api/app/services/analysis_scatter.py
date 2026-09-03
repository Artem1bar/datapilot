"""The scatter operation: points, a fitted line, colors, sizes, and a reading.

Split out of :mod:`app.services.analysis_executor` because a scatter is the
one operation whose chart is not its result table. It carries its own sample
of points, the groups that color them, the column that sizes them, and the
interpretation of the fit — enough to be a module of its own.

The invariants this module holds: the fit is computed on every complete row
and never on the sample; every color group among the complete rows is named
even when the sample happens to miss it; a missing color label is kept as a
group rather than dropped; and a missing size excludes the row, because a
bubble without a size cannot be drawn and a point that is not drawn must not
shape the line.
"""

from __future__ import annotations

import warnings
from typing import Any

import pandas as pd
from scipy import stats

from app.services.analysis_interpretation import interpret_scatter
from app.services.analysis_result import (
    MISSING_GROUP_LABEL,
    ExecutionError,
    OperationResult,
    PlotPoints,
    frame_to_result,
    to_python,
)
from app.services.analysis_spec import MAX_SCATTER_GROUPS

# How many points a scatter plot carries, and the seed that picks them when
# the frame has more. The result table's cap is a preview of a table; a plot
# of the first 200 rows of a file sorted by date is a picture of the sort
# order, not of the relationship, so the plot draws a seeded random sample
# instead. The fit is never sampled: it is computed on every complete row.
MAX_SCATTER_POINTS = 2_000
SCATTER_SAMPLE_SEED = 0


def _group_labels(values: pd.Series) -> pd.Series:
    """Color labels as text, with missing values named rather than dropped."""
    return values.astype("string").fillna(MISSING_GROUP_LABEL).astype(object)


def _legend_order(labels: set[str]) -> tuple[str, ...]:
    """Named groups sorted, the missing bucket last."""
    named = sorted(labels - {MISSING_GROUP_LABEL})
    return (*named, MISSING_GROUP_LABEL) if MISSING_GROUP_LABEL in labels else tuple(named)


def _plot_points(
    subset: pd.DataFrame, x: str, y: str, group: str | None, size: str | None = None
) -> PlotPoints:
    """Every complete row, or a seeded random sample when there are too many.

    The group list and the size range are taken from every row, not the
    sample: a category with three rows in fifty thousand is still a category,
    and a legend that omits it says the data has one fewer group than it does.
    """
    total = len(subset)
    sampled = total > MAX_SCATTER_POINTS
    drawn = (
        subset.sample(n=MAX_SCATTER_POINTS, random_state=SCATTER_SAMPLE_SEED).sort_index()
        if sampled
        else subset
    )
    columns = [x, y] + ([size] if size else []) + ([group] if group else [])
    rows = [
        [to_python(value) for value in row]
        for row in drawn[columns].itertuples(index=False, name=None)
    ]

    groups: tuple[str, ...] = ()
    unplotted: tuple[str, ...] = ()
    if group:
        groups = _legend_order({str(label) for label in subset[group]})
        shown = {row[-1] for row in rows}
        unplotted = tuple(label for label in groups if label not in shown)
    size_range = (to_python(subset[size].min()), to_python(subset[size].max())) if size else None
    return PlotPoints(
        x=x,
        y=y,
        group=group,
        rows=rows,
        total=total,
        sampled=sampled,
        seed=SCATTER_SAMPLE_SEED if sampled else None,
        groups=groups,
        unplotted_groups=unplotted,
        size=size,
        size_range=size_range,
    )


def _unplotted_note(plot: PlotPoints, labels: pd.Series) -> str:
    """Name the groups the sample does not show, with their true sizes."""
    counts = labels.value_counts()
    named = ", ".join(
        f"{group!r} ({int(counts.get(group, 0)):,} row{'' if counts.get(group, 0) == 1 else 's'})"
        for group in plot.unplotted_groups
    )
    return (
        f"The plotted sample has no points from {named}; "
        "the legend, the group count and the fitted line still include them."
    )


def op_scatter_with_fit(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    x_col = params["x"]
    y_col = params["y"]
    size = params.get("size")
    group = params.get("color_by")

    # A bubble with no size cannot be drawn, and a point that is not drawn
    # must not shape the line either — so a missing size excludes the row.
    # A missing color label only loses its color.
    required = [x_col, y_col] + ([size] if size else [])
    columns = required + ([group] if group else [])
    subset = df[columns].dropna(subset=required)
    excluded = len(df) - len(subset)
    if len(subset) < 3:
        raise ExecutionError(
            f"scatter_with_fit: only {len(subset)} complete row(s); need at least 3"
        )

    labels: pd.Series | None = None
    if group:
        labels = _group_labels(subset[group])
        # Distinct real values, as the validator counts them; the missing
        # bucket is drawn in a neutral color and does not use up a hue.
        distinct = int(subset[group].dropna().nunique())
        if distinct > MAX_SCATTER_GROUPS:
            raise ExecutionError(
                f"scatter_with_fit: color_by {group!r} has {distinct} distinct values; "
                f"at most {MAX_SCATTER_GROUPS} can be colored"
            )
        subset = subset.assign(**{group: labels})

    # A constant x has no slope: scipy returns NaN with a RuntimeWarning, and
    # the NaN becomes "not computed" downstream. The warning adds nothing.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = stats.linregress(subset[x_col], subset[y_col])
    stats_payload = {
        "slope": round(float(result.slope), 6),
        "intercept": round(float(result.intercept), 6),
        "r": round(float(result.rvalue), 4),
        "r_squared": round(float(result.rvalue**2), 4),
        "p_value": float(result.pvalue),
        "std_err": round(float(result.stderr), 6),
        "fit": f"{y_col} = {result.slope:.4g} × {x_col} + {result.intercept:.4g}",
    }

    plot = _plot_points(subset, x_col, y_col, group, size)
    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    if plot.sampled:
        notes.append(
            f"Plotted a random sample of {MAX_SCATTER_POINTS:,} of {plot.total:,} complete "
            f"rows (seed {plot.seed}); the fitted line is computed on all of them."
        )
    if plot.unplotted_groups and labels is not None:
        notes.append(_unplotted_note(plot, labels))
    # Between the table cap and the sample cap, frame_to_result's own note
    # ("Showing the first 200 of N result rows") already says what is shown.
    return frame_to_result(
        subset,
        op="scatter_with_fit",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes,
        stats_payload=stats_payload,
        plot=plot,
    )


# The fit statistics a scatter chart carries, so the frontend can draw the
# line the executor fitted rather than fit one of its own from the sample.
_FIT_KEYS = ("slope", "intercept", "r", "r_squared", "p_value", "std_err")


def scatter_chart(result: OperationResult, plot: PlotPoints) -> dict[str, Any]:
    """A scatter's config: every plotted point, the fit, and the color groups.

    The generic path plots the result table, which for a scatter is a 200-row
    preview of the points. The chart gets the plot sample instead, and the
    line computed on every complete row travels with it, as does a reading of
    what the fit means. A size column makes it a bubble chart; a request for
    a bubble chart without one draws a scatter rather than inventing a size.
    """
    keys = ["x", "y"] + (["size"] if plot.size else []) + (["group"] if plot.group else [])
    data = [dict(zip(keys, row, strict=True)) for row in plot.rows]

    return {
        "chart_type": "bubble" if plot.size else "scatter",
        "title": result.label,
        "x_field": plot.x,
        "y_field": plot.y,
        "data": data,
        "options": {
            "computed": True,
            "n": result.n,
            "n_excluded": result.n_excluded,
            "plotted": len(plot.rows),
            "total_points": plot.total,
            "sampled": plot.sampled,
            "sample_seed": plot.seed,
            "group_field": plot.group,
            "groups": list(plot.groups),
            "unplotted_groups": list(plot.unplotted_groups),
            "size_field": plot.size,
            "size_range": list(plot.size_range) if plot.size_range else None,
            "fit": {key: result.stats.get(key) for key in _FIT_KEYS},
            "interpretation": interpret_scatter(result),
        },
    }
