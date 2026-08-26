"""Deterministic execution of a validated analysis spec.

Step 3 of the analysis pipeline. Every number the user sees originates here, in
pandas and scipy over the full dataframe — never from a model. The spec reaching
this module has already been validated against the dataset's real columns by
:mod:`app.services.analysis_spec`, so execution can assume columns exist and
aggregations match dtypes.

Each operation returns an :class:`OperationResult` carrying its own provenance:
how many rows it saw, how many it excluded and why. That is what lets the
narrator state "excluding 412 rows with missing income" instead of quietly
reporting a mean over an unknown denominator.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analysis_spec import ColumnRoles  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)

# Result tables are capped so a groupby over a high-cardinality column cannot
# return 50,000 rows to the UI or the narrator prompt.
MAX_RESULT_ROWS = 200

# Default row counts for operations that take an optional limit.
DEFAULT_TOP_N = 10
DEFAULT_VALUE_COUNTS = 20
DEFAULT_BINS = 10


@dataclass(frozen=True)
class OperationResult:
    """One computed table, with the provenance needed to report it honestly."""

    op: str
    label: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    n: int
    n_excluded: int = 0
    notes: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_table(self) -> dict[str, Any]:
        """Render as the API's table shape (unchanged from the previous contract)."""
        return {"columns": self.columns, "rows": self.rows, "total_rows": self.total_rows}


class ExecutionError(RuntimeError):
    """An operation failed at runtime despite passing validation."""


def _py(value: Any) -> Any:
    """Coerce numpy/pandas scalars to JSON-safe Python values."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        as_float = float(value)
        return None if math.isnan(as_float) or math.isinf(as_float) else round(as_float, 6)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value) if np.isscalar(value) else False:
        return None
    return value if isinstance(value, (str, int)) else str(value)


def _round(value: Any, places: int = 4) -> float | None:
    """Round a statistic, returning None for NaN/inf rather than a bad float.

    Degenerate inputs produce non-finite statistics — a t-test over two
    zero-variance groups returns NaN — and NaN is not valid JSON. Emitting None
    lets the narrator say the test could not be computed instead of the API
    serializing a value no JSON parser accepts.
    """
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return round(as_float, places)


def _clean_stats(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively replace non-finite floats in a statistics payload with None."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, float):
            cleaned[key] = _round(value, 6)
        elif isinstance(value, dict):
            cleaned[key] = _clean_stats(value)
        elif isinstance(value, list):
            cleaned[key] = [_clean_stats(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


def _frame_to_result(
    df: pd.DataFrame,
    *,
    op: str,
    label: str,
    n: int,
    n_excluded: int = 0,
    notes: list[str] | None = None,
    stats_payload: dict[str, Any] | None = None,
) -> OperationResult:
    """Package a result frame, truncating to ``MAX_RESULT_ROWS``."""
    total = len(df)
    truncated = df.head(MAX_RESULT_ROWS)
    all_notes = list(notes or [])
    if total > MAX_RESULT_ROWS:
        all_notes.append(f"Showing the first {MAX_RESULT_ROWS} of {total} result rows.")
    return OperationResult(
        op=op,
        label=label,
        columns=[str(c) for c in truncated.columns],
        rows=[[_py(v) for v in row] for row in truncated.itertuples(index=False, name=None)],
        total_rows=total,
        n=n,
        n_excluded=n_excluded,
        notes=all_notes,
        stats=_clean_stats(stats_payload) if stats_payload else {},
    )


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def apply_filter(
    df: pd.DataFrame, spec_filter: dict[str, Any] | None
) -> tuple[pd.DataFrame, str | None]:
    """Apply the spec's optional row filter, returning the frame and a description."""
    if not spec_filter:
        return df, None

    column = spec_filter["column"]
    operator = spec_filter["operator"]
    value = spec_filter.get("value")
    series = df[column]

    if operator == "is_null":
        mask = series.isna()
    elif operator == "is_not_null":
        mask = series.notna()
    elif operator == "contains":
        mask = series.astype(str).str.contains(str(value), case=False, na=False)
    elif operator == "not_contains":
        mask = ~series.astype(str).str.contains(str(value), case=False, na=False)
    elif operator in (">", ">=", "<", "<="):
        numeric = pd.to_numeric(series, errors="coerce")
        comparison = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.isna(comparison):
            raise ExecutionError(f"Filter value {value!r} is not numeric for operator {operator!r}")
        mask = {
            ">": numeric > comparison,
            ">=": numeric >= comparison,
            "<": numeric < comparison,
            "<=": numeric <= comparison,
        }[operator]
    elif operator == "==":
        mask = series == value
    else:  # "!="
        mask = series != value

    filtered = df[mask.fillna(False)]
    description = f"{column} {operator} {value!r}" if value is not None else f"{column} {operator}"
    return filtered, f"Filtered to rows where {description} ({len(filtered)} of {len(df)} rows)."


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _op_describe(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    columns = params.get("columns") or [
        str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
    ]
    if not columns:
        raise ExecutionError("describe: no numeric columns to summarize")
    described = df[columns].describe().reset_index().rename(columns={"index": "statistic"})
    return _frame_to_result(described, op="describe", label=label, n=len(df))


def _op_groupby_aggregate(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    group_by = params["group_by"]
    column = params["column"]
    agg = params["agg"]

    before = len(df)
    subset = df.dropna(subset=group_by)
    # count/nunique are meaningful over nulls in the target column; the numeric
    # aggregations are not, so only those drop null targets.
    if agg not in ("count", "nunique"):
        subset = subset.dropna(subset=[column])
    excluded = before - len(subset)

    if subset.empty:
        raise ExecutionError(
            f"groupby_aggregate: no rows remain after dropping nulls in {column!r}"
        )

    grouped = subset.groupby(group_by, dropna=True)[column].agg(agg).reset_index()
    grouped = grouped.rename(columns={column: f"{column}_{agg}"})
    grouped = grouped.sort_values(f"{column}_{agg}", ascending=False)

    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    return _frame_to_result(
        grouped,
        op="groupby_aggregate",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes,
    )


def _op_value_counts(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column = params["column"]
    top_n = params.get("top_n", DEFAULT_VALUE_COUNTS)
    normalize = params.get("normalize", False)

    counts = df[column].value_counts(normalize=normalize, dropna=True).head(top_n)
    frame = counts.reset_index()
    frame.columns = [column, "proportion" if normalize else "count"]
    excluded = int(df[column].isna().sum())
    notes = [f"Excluded {excluded} row(s) with a missing {column}."] if excluded else []
    return _frame_to_result(
        frame,
        op="value_counts",
        label=label,
        n=len(df) - excluded,
        n_excluded=excluded,
        notes=notes,
    )


def _op_crosstab(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    row_col = params["row"]
    col_col = params["column"]
    normalize = params.get("normalize", False)

    table = pd.crosstab(df[row_col], df[col_col], normalize="index" if normalize else False)
    # Chi-square needs raw counts, so recompute unnormalized when normalizing.
    counts = table if not normalize else pd.crosstab(df[row_col], df[col_col])
    stats_payload: dict[str, Any] = {}
    if counts.shape[0] > 1 and counts.shape[1] > 1 and counts.to_numpy().sum() > 0:
        try:
            chi2, p_value, dof, _ = stats.chi2_contingency(counts)
            stats_payload = {
                "test": "chi-square test of independence",
                "chi2": round(float(chi2), 4),
                "p_value": round(float(p_value), 6),
                "dof": int(dof),
            }
        except ValueError as exc:  # zero-frequency rows/columns
            logger.info("crosstab: chi-square not computed (%s)", exc)

    flat = table.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    return _frame_to_result(
        flat, op="crosstab", label=label, n=len(df), stats_payload=stats_payload
    )


def _op_histogram(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column = params["column"]
    bins = params.get("bins", DEFAULT_BINS)
    series = df[column].dropna()
    excluded = len(df) - len(series)
    if series.empty:
        raise ExecutionError(f"histogram: column {column!r} has no non-null values")

    counts, edges = np.histogram(series, bins=bins)
    frame = pd.DataFrame(
        {
            "bin": [f"{edges[i]:.4g} – {edges[i + 1]:.4g}" for i in range(len(counts))],
            "count": counts,
        }
    )
    notes = [f"Excluded {excluded} row(s) with a missing {column}."] if excluded else []
    return _frame_to_result(
        frame, op="histogram", label=label, n=len(series), n_excluded=excluded, notes=notes
    )


def _op_top_n(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column = params["column"]
    by = params["by"]
    n = params.get("n", DEFAULT_TOP_N)
    ascending = params.get("ascending", False)

    subset = df[[column, by]].dropna(subset=[by])
    excluded = len(df) - len(subset)
    ordered = subset.sort_values(by, ascending=ascending).head(n)
    notes = [f"Excluded {excluded} row(s) with a missing {by}."] if excluded else []
    return _frame_to_result(
        ordered, op="top_n", label=label, n=len(subset), n_excluded=excluded, notes=notes
    )


def _op_pivot(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    index = params["index"]
    columns = params["columns"]
    values = params["values"]
    agg = params["agg"]

    table = pd.pivot_table(df, index=index, columns=columns, values=values, aggfunc=agg)
    flat = table.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    return _frame_to_result(flat, op="pivot", label=label, n=len(df))


def _op_resample(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    date_column = params["date_column"]
    column = params["column"]
    freq = params["freq"]
    agg = params["agg"]

    subset = df[[date_column, column]].dropna()
    excluded = len(df) - len(subset)
    if subset.empty:
        raise ExecutionError(f"resample: no rows with both {date_column!r} and {column!r}")

    series = subset.set_index(date_column)[column].resample(freq).agg(agg)
    frame = series.reset_index()
    frame.columns = [date_column, f"{column}_{agg}"]
    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    return _frame_to_result(
        frame, op="resample", label=label, n=len(subset), n_excluded=excluded, notes=notes
    )


def _op_correlation_matrix(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    columns = params["columns"]
    method = params.get("method", "pearson")

    subset = df[columns].dropna()
    excluded = len(df) - len(subset)
    if len(subset) < 3:
        raise ExecutionError(
            f"correlation_matrix: only {len(subset)} complete row(s) across {columns}; need at least 3"
        )

    matrix = subset.corr(method=method).round(4)
    flat = matrix.reset_index().rename(columns={"index": "column"})
    flat.columns = [str(c) for c in flat.columns]

    # Pairwise p-values make the difference between "these move together" and
    # "this correlation is indistinguishable from zero at this sample size".
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(columns):
        for b in columns[i + 1 :]:
            if method == "pearson":
                r, p = stats.pearsonr(subset[a], subset[b])
            elif method == "spearman":
                r, p = stats.spearmanr(subset[a], subset[b])
            else:
                r, p = stats.kendalltau(subset[a], subset[b])
            pairs.append({"x": a, "y": b, "r": round(float(r), 4), "p_value": round(float(p), 6)})

    notes = (
        [f"Excluded {excluded} row(s) with missing values in any selected column."]
        if excluded
        else []
    )
    return _frame_to_result(
        flat,
        op="correlation_matrix",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes,
        stats_payload={"method": method, "pairs": pairs},
    )


def _op_scatter_with_fit(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    x_col = params["x"]
    y_col = params["y"]

    subset = df[[x_col, y_col]].dropna()
    excluded = len(df) - len(subset)
    if len(subset) < 3:
        raise ExecutionError(
            f"scatter_with_fit: only {len(subset)} complete row(s); need at least 3"
        )

    result = stats.linregress(subset[x_col], subset[y_col])
    stats_payload = {
        "slope": round(float(result.slope), 6),
        "intercept": round(float(result.intercept), 6),
        "r": round(float(result.rvalue), 4),
        "r_squared": round(float(result.rvalue**2), 4),
        "p_value": round(float(result.pvalue), 6),
        "std_err": round(float(result.stderr), 6),
        "fit": f"{y_col} = {result.slope:.4g} × {x_col} + {result.intercept:.4g}",
    }
    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    # Scatter payloads are capped by _frame_to_result; the fit is computed on all rows.
    return _frame_to_result(
        subset,
        op="scatter_with_fit",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes + ["The fitted line is computed on all complete rows, not just those shown."],
        stats_payload=stats_payload,
    )


def _op_group_comparison(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    group_by = params["group_by"]
    column = params["column"]

    subset = df[[group_by, column]].dropna()
    excluded = len(df) - len(subset)
    if subset.empty:
        raise ExecutionError(f"group_comparison: no complete rows for {group_by!r} and {column!r}")

    grouped = subset.groupby(group_by)[column]
    summary = grouped.agg(["count", "mean", "std", "median"]).reset_index()

    # 95% CI on each group mean — the point of a comparison is whether the
    # groups are distinguishable, which bare means do not show.
    ci_low: list[float | None] = []
    ci_high: list[float | None] = []
    for _, row in summary.iterrows():
        n, mean, sd = row["count"], row["mean"], row["std"]
        if n > 1 and pd.notna(sd) and sd > 0:
            margin = stats.t.ppf(0.975, n - 1) * (sd / math.sqrt(n))
            ci_low.append(round(float(mean - margin), 4))
            ci_high.append(round(float(mean + margin), 4))
        else:
            ci_low.append(None)
            ci_high.append(None)
    summary["ci95_low"] = ci_low
    summary["ci95_high"] = ci_high

    groups = [g.to_numpy() for _, g in grouped if len(g) > 1]
    stats_payload: dict[str, Any] = {}
    # A significance test needs variance somewhere. With every group constant,
    # scipy returns NaN and warns; say so plainly instead of reporting an
    # uncomputable test.
    if groups and all(float(np.std(g)) == 0.0 for g in groups):
        stats_payload = {
            "test": "not computed",
            "reason": "every group has zero variance, so no significance test applies",
        }
    elif len(groups) == 2:
        t_stat, p_value = stats.ttest_ind(groups[0], groups[1], equal_var=False)
        stats_payload = {
            "test": "Welch's t-test (two groups, unequal variance)",
            "statistic": round(float(t_stat), 4),
            "p_value": round(float(p_value), 6),
        }
    elif len(groups) > 2:
        f_stat, p_value = stats.f_oneway(*groups)
        stats_payload = {
            "test": "one-way ANOVA",
            "statistic": round(float(f_stat), 4),
            "p_value": round(float(p_value), 6),
            "note": "ANOVA assumes similar variances across groups; check the std column.",
        }

    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    return _frame_to_result(
        summary,
        op="group_comparison",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes,
        stats_payload=stats_payload,
    )


_DISPATCH = {
    "describe": _op_describe,
    "groupby_aggregate": _op_groupby_aggregate,
    "value_counts": _op_value_counts,
    "crosstab": _op_crosstab,
    "histogram": _op_histogram,
    "top_n": _op_top_n,
    "pivot": _op_pivot,
    "resample": _op_resample,
    "correlation_matrix": _op_correlation_matrix,
    "scatter_with_fit": _op_scatter_with_fit,
    "group_comparison": _op_group_comparison,
}


def execute_spec(df: pd.DataFrame, spec: dict[str, Any]) -> list[OperationResult]:
    """Run every operation in a validated *spec* against *df*.

    A single failing operation is recorded as a note on the remaining results
    rather than aborting the whole answer — a two-operation question where one
    half works is still worth returning.

    Raises ``ExecutionError`` only if no operation succeeds.
    """
    filtered, filter_note = apply_filter(df, spec.get("filter"))

    results: list[OperationResult] = []
    failures: list[str] = []
    for index, operation in enumerate(spec.get("operations", [])):
        op = operation["op"]
        label = str(operation.get("label") or op.replace("_", " ").title())
        try:
            result = _DISPATCH[op](filtered, operation.get("params", {}), label)
        except ExecutionError as exc:
            failures.append(f"operations[{index}] ({op}): {exc}")
            continue
        except Exception as exc:  # pandas/scipy raising on an edge case
            logger.exception("Analysis operation %s failed", op)
            failures.append(f"operations[{index}] ({op}): {type(exc).__name__}: {exc}")
            continue

        if filter_note:
            result.notes.insert(0, filter_note)
        results.append(result)

    if not results:
        raise ExecutionError("; ".join(failures) or "spec contained no operations")

    if failures:
        results[0].notes.append("Some requested operations failed: " + "; ".join(failures))
    return results


# Which result column to plot when the spec does not name one. Defaulting to
# "the second column" is wrong for multi-column summaries: group_comparison
# returns [group, count, mean, std, ...], so the naive default would plot group
# sizes under a title promising averages.
_DEFAULT_CHART_Y: dict[str, str] = {
    "group_comparison": "mean",
    "describe": "mean",
}


def build_chart(
    chart: dict[str, Any] | None, results: list[OperationResult]
) -> dict[str, Any] | None:
    """Render a chart config from a computed result table.

    The chart's data is the executed result, so what is plotted is exactly what
    was measured. The y column is chosen in this order: the spec's ``y`` if it
    names a real result column, the per-operation default, then the second
    column. Returns None when the spec asked for no chart or the referenced
    operation did not survive execution.
    """
    if not chart:
        return None
    index = chart.get("operation", 0)
    if not isinstance(index, int) or not 0 <= index < len(results):
        return None

    result = results[index]
    if len(result.columns) < 2 or not result.rows:
        return None

    x_field = result.columns[0]
    requested = chart.get("y")
    default = _DEFAULT_CHART_Y.get(result.op)
    if isinstance(requested, str) and requested in result.columns:
        y_field = requested
    elif default and default in result.columns:
        y_field = default
    else:
        y_field = result.columns[1]

    y_index = result.columns.index(y_field)
    return {
        "chart_type": chart.get("type", "bar"),
        "title": result.label,
        "x_field": x_field,
        "y_field": y_field,
        "data": [{"x": row[0], "y": row[y_index]} for row in result.rows],
        "options": {"computed": True, "n": result.n},
    }
