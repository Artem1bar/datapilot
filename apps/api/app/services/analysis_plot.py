"""A scatter plot on demand, without a planner.

The chat pipeline lets a model choose *what* to compute. A plot request already
says what: these two columns, optionally colored by a third. So the spec is
built here rather than asked for, and everything after that — validation
against the dataset's real columns, execution, the chart, the provenance
record, the Python and R export — is the same code path a chat answer takes.
A line drawn through the points is still a computed line, and it arrives with
the same denominators and the same reproducible script.

No model runs anywhere in this module. The one paragraph of prose is assembled
from the computed statistics, not written about them.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.analysis import exported_code
from app.services.analysis_executor import ExecutionError, build_chart, execute_spec
from app.services.analysis_interpretation import interpret_scatter
from app.services.analysis_provenance import build_provenance
from app.services.analysis_result import OperationResult
from app.services.analysis_spec import ColumnRoles, validate_spec


class ScatterPlotError(ValueError):
    """The request names columns the dataset cannot plot, or too few rows.

    Carries every problem at once, the way the spec validator reports them, so
    a caller can show all of them rather than one per round trip.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def scatter_question(x: str, y: str, color_by: str | None = None, size: str | None = None) -> str:
    """The request in words, as the provenance record's question."""
    question = f"Scatter plot of {y} against {x}"
    if color_by:
        question += f", colored by {color_by}"
    if size:
        question += f", sized by {size}"
    return question


def scatter_spec(
    x: str, y: str, color_by: str | None = None, size: str | None = None
) -> dict[str, Any]:
    """The analysis spec a planner would have written for this request."""
    params: dict[str, Any] = {"x": x, "y": y}
    if size:
        params["size"] = size
    if color_by:
        params["color_by"] = color_by
    return {
        "rationale": "The user asked for this plot directly; no planning was needed.",
        "filter": None,
        "operations": [
            {"op": "scatter_with_fit", "label": f"{y} vs {x}", "params": params},
        ],
        "chart": {"type": "bubble" if size else "scatter", "operation": 0},
    }


def _number(value: Any, digits: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "not computed"
    return f"{value:.{digits}g}"


def _equation(x: str, y: str, slope: Any, intercept: Any) -> str:
    if not isinstance(slope, (int, float)) or not isinstance(intercept, (int, float)):
        return f"{y} = (not computed)"
    sign = "−" if intercept < 0 else "+"
    return f"{y} = {slope:.4g} × {x} {sign} {abs(intercept):.4g}"


def describe_scatter(result: OperationResult) -> str:
    """The fit and its denominator, in one paragraph built from the numbers."""
    plot, stats = result.plot, result.stats
    if plot is None:  # pragma: no cover - a scatter result always carries its points
        raise ValueError("describe_scatter needs a result with plot points")

    denominator = f"{result.n:,} complete rows"
    if result.n_excluded:
        denominator += f" ({result.n_excluded:,} excluded for missing values)"
    sentences = [
        f"Scatter plot of {plot.y} against {plot.x} over {denominator}.",
        (
            f"OLS fit: {_equation(plot.x, plot.y, stats.get('slope'), stats.get('intercept'))}; "
            f"R² = {_number(stats.get('r_squared'), 3)}; "
            f"slope p = {_number(stats.get('p_value'), 2)}, "
            f"standard error {_number(stats.get('std_err'), 3)}."
        ),
    ]
    if plot.sampled:
        sentences.append(
            f"The chart shows a random sample of {len(plot.rows):,} of the {plot.total:,} "
            "points; the line is fitted to all of them."
        )
    if plot.group:
        sentences.append(f"Points are colored by {plot.group} ({len(plot.groups)} groups).")
        if plot.unplotted_groups:
            names = ", ".join(plot.unplotted_groups)
            sentences.append(f"The sample shows no points from {names}.")
    if plot.size and plot.size_range:
        low, high = plot.size_range
        sentences.append(
            f"Bubble area shows {plot.size} ({_number(low, 4)} to {_number(high, 4)})."
        )

    # The reading's headline and its significance sentence; the chart card
    # carries the full reading with its caveats.
    reading = interpret_scatter(result)["summary"]
    headline = [reading[0]] + [s for s in reading[1:] if "distinguish" in s]
    sentences.append("Reading it: " + " ".join(headline))
    return " ".join(sentences)


def scatter_plot(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    color_by: str | None = None,
    size: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Plot *y* against *x* over every row of *df*, with an OLS line.

    A *size* column makes it a bubble chart.

    Returns the chat turn's shape — ``{answer, charts, tables, provenance}`` —
    so the frontend records a plot the way it records an answer.

    Raises :class:`ScatterPlotError` when the columns cannot be plotted. This is
    a sync function — call via ``asyncio.to_thread()`` from async code.
    """
    spec = scatter_spec(x, y, color_by, size)
    question = scatter_question(x, y, color_by, size)

    problems = validate_spec(spec, ColumnRoles.from_dataframe(df))
    if problems:
        raise ScatterPlotError(problems)

    try:
        results = execute_spec(df, spec)
    except ExecutionError as exc:
        raise ScatterPlotError([str(exc)]) from exc

    chart = build_chart(spec["chart"], results)
    provenance = build_provenance(
        question=question, spec=spec, results=results, df=df, filename=filename
    )
    provenance["code"] = exported_code(spec, question)

    return {
        "answer": describe_scatter(results[0]),
        "charts": [chart] if chart else [],
        "tables": [result.to_table() for result in results],
        "provenance": provenance,
    }
