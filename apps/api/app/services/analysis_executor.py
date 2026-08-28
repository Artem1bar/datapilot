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
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analysis_categorical import CATEGORICAL_OPERATIONS
from app.services.analysis_inference import INFERENCE_OPERATIONS
from app.services.analysis_regression import REGRESSION_OPERATIONS
from app.services.analysis_result import (  # noqa: F401  (re-exported for callers)
    MAX_RESULT_ROWS,
    ExecutionError,
    OperationResult,
    frame_to_result,
    to_python,
    with_spec_index,
)
from app.services.analysis_spec import ColumnRoles  # noqa: F401  (re-exported for callers)
from app.services.analysis_survey import SURVEY_OPERATIONS
from app.services.analysis_timeseries import TIMESERIES_OPERATIONS

logger = logging.getLogger(__name__)


# Default row counts for operations that take an optional limit.
DEFAULT_TOP_N = 10
DEFAULT_VALUE_COUNTS = 20
DEFAULT_BINS = 10

# A group of one has no variance to contribute, so no comparison test can use
# it; below this size a group is described but not tested.
MIN_TESTABLE_GROUP_N = 2

# How many group names a prose sentence lists before it summarizes the rest.
# A group_comparison over a high-cardinality column would otherwise paste a
# hundred category names into a note.
MAX_NAMED_GROUPS = 5


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
    note = f"Filtered to rows where {description} ({len(filtered)} of {len(df)} rows)."

    # pandas semantics: NaN != value is True, so "!=" keeps rows whose value is
    # missing while "==" drops them. The behaviour is left as pandas defines it
    # — the code export reproduces it exactly — but it silently changes the
    # denominator of every operation downstream, so it is stated rather than
    # left for the reader to infer.
    if operator == "!=":
        kept_null = int(series.isna().sum())
        if kept_null:
            note += f" Includes {kept_null} row(s) where {column} is missing."
    return filtered, note


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
    return frame_to_result(described, op="describe", label=label, n=len(df))


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
    return frame_to_result(
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
    return frame_to_result(
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

    # pd.crosstab drops rows null in either column, so the denominator is the
    # complete rows — not len(df). Dropping them here rather than letting
    # pandas do it silently is what lets n, n_excluded and the note agree with
    # the table and with the chi-square attached to it.
    subset = df[[row_col, col_col]].dropna()
    excluded = len(df) - len(subset)

    table = pd.crosstab(subset[row_col], subset[col_col], normalize="index" if normalize else False)
    # Chi-square needs raw counts, so recompute unnormalized when normalizing.
    counts = table if not normalize else pd.crosstab(subset[row_col], subset[col_col])
    stats_payload: dict[str, Any] = {}
    if counts.shape[0] > 1 and counts.shape[1] > 1 and counts.to_numpy().sum() > 0:
        try:
            chi2, p_value, dof, _ = stats.chi2_contingency(counts)
            stats_payload = {
                "test": "chi-square test of independence",
                "chi2": round(float(chi2), 4),
                # Not pre-rounded: json_safe keeps significant figures below
                # 1e-4, and round(p, 6) would hand it a 0.0 to faithfully
                # report as p = 0 — certainty no test can support.
                "p_value": float(p_value),
                "dof": int(dof),
            }
        except ValueError as exc:  # zero-frequency rows/columns
            logger.info("crosstab: chi-square not computed (%s)", exc)

    flat = table.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    return frame_to_result(
        flat,
        op="crosstab",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes,
        stats_payload=stats_payload,
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
    return frame_to_result(
        frame, op="histogram", label=label, n=len(series), n_excluded=excluded, notes=notes
    )


def _op_top_n(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    column = params["column"]
    by = params["by"]
    n = params.get("n", DEFAULT_TOP_N)
    ascending = params.get("ascending", False)

    # "Top 10 revenues by revenue" is a plausible plan and the validator allows
    # it, but df[[c, c]] builds a duplicate column and dropna(subset=[c]) then
    # refuses to work on an ambiguous label. Select each column once.
    wanted = [column] if column == by else [column, by]
    subset = df[wanted].dropna(subset=[by])
    excluded = len(df) - len(subset)
    ordered = subset.sort_values(by, ascending=ascending).head(n)
    notes = [f"Excluded {excluded} row(s) with a missing {by}."] if excluded else []
    return frame_to_result(
        ordered, op="top_n", label=label, n=len(subset), n_excluded=excluded, notes=notes
    )


def _op_pivot(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    index = params["index"]
    columns = params["columns"]
    values = params["values"]
    agg = params["agg"]

    # pivot_table drops rows with a null key, and the numeric aggregations
    # ignore null values, so the table's denominator is the complete rows.
    # count/nunique are meaningful over a null target, matching the rule in
    # _op_groupby_aggregate.
    keys = [*index, columns] if isinstance(index, list) else [index, columns]
    subset = df.dropna(subset=keys)
    if agg not in ("count", "nunique"):
        subset = subset.dropna(subset=[values])
    excluded = len(df) - len(subset)
    if subset.empty:
        raise ExecutionError(f"pivot: no rows remain after dropping nulls in {keys + [values]}")

    table = pd.pivot_table(subset, index=index, columns=columns, values=values, aggfunc=agg)
    flat = table.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    return frame_to_result(
        flat, op="pivot", label=label, n=len(subset), n_excluded=excluded, notes=notes
    )


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
    return frame_to_result(
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
            # The p-value goes through unrounded so json_safe can keep its
            # significant figures; see _op_crosstab.
            pairs.append({"x": a, "y": b, "r": round(float(r), 4), "p_value": float(p)})

    notes = (
        [f"Excluded {excluded} row(s) with missing values in any selected column."]
        if excluded
        else []
    )
    return frame_to_result(
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
        "p_value": float(result.pvalue),
        "std_err": round(float(result.stderr), 6),
        "fit": f"{y_col} = {result.slope:.4g} × {x_col} + {result.intercept:.4g}",
    }
    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    # Scatter payloads are capped by frame_to_result; the fit is computed on all rows.
    return frame_to_result(
        subset,
        op="scatter_with_fit",
        label=label,
        n=len(subset),
        n_excluded=excluded,
        notes=notes + ["The fitted line is computed on all complete rows, not just those shown."],
        stats_payload=stats_payload,
    )


def _name_groups(labels: list[str]) -> str:
    """Render a group list for prose, without pasting a hundred category names."""
    if len(labels) <= MAX_NAMED_GROUPS:
        return ", ".join(labels)
    shown = ", ".join(labels[:MAX_NAMED_GROUPS])
    return f"{shown} and {len(labels) - MAX_NAMED_GROUPS} more"


def _comparison_test(
    labels: list[str], groups: list[np.ndarray], too_small: list[str]
) -> dict[str, Any]:
    """Pick the test the usable groups support, and record what it left out.

    Every branch carries ``groups_compared`` and ``groups_excluded`` so the
    statistic can never be read as covering the whole summary table when it
    does not. The two no-test branches return a stated reason rather than an
    empty payload: "no test ran, and here is why" is information, silence is
    not.
    """
    context = {"groups_compared": labels, "groups_excluded": too_small}
    if len(groups) < 2:
        excluded = f" ({_name_groups(too_small)})" if too_small else ""
        return {
            "test": "not computed",
            "reason": (
                f"only {len(groups)} group(s) hold at least {MIN_TESTABLE_GROUP_N} values, so "
                f"there is nothing to compare; {len(too_small)} group(s){excluded} were too "
                f"small to test"
            ),
            **context,
        }
    # A significance test needs variance somewhere. With every group constant,
    # scipy returns NaN and warns; say so plainly instead of reporting an
    # uncomputable test.
    if all(float(np.std(values)) == 0.0 for values in groups):
        return {
            "test": "not computed",
            "reason": "every group has zero variance, so no significance test applies",
            **context,
        }
    if len(groups) == 2:
        t_stat, p_value = stats.ttest_ind(groups[0], groups[1], equal_var=False)
        return {
            "test": f"Welch's t-test ({labels[0]} vs {labels[1]}, unequal variance)",
            "statistic": round(float(t_stat), 4),
            "p_value": float(p_value),
            **context,
        }
    f_stat, p_value = stats.f_oneway(*groups)
    return {
        "test": f"one-way ANOVA across {len(groups)} groups ({_name_groups(labels)})",
        "statistic": round(float(f_stat), 4),
        "p_value": float(p_value),
        "note": "ANOVA assumes similar variances across groups; check the std column.",
        **context,
    }


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

    # A group of one contributes no variance, so no two-sample or one-way test
    # can use it. Dropping it is right; dropping it silently is not — the
    # summary table and the chart still show it, so the payload names the
    # groups the test compared, the groups it did not, and reports n as the
    # rows the statistic actually saw.
    testable = [(str(key), values.to_numpy()) for key, values in grouped if len(values) > 1]
    too_small = [str(key) for key, values in grouped if len(values) <= 1]
    tested_labels = [name for name, _ in testable]
    groups = [values for _, values in testable]
    tested_rows = int(sum(values.size for values in groups))

    stats_payload = _comparison_test(tested_labels, groups, too_small)
    ran_a_test = stats_payload.get("p_value") is not None

    notes = [f"Excluded {excluded} row(s) with missing values."] if excluded else []
    if too_small and ran_a_test:
        notes.append(
            f"{len(too_small)} group(s) ({_name_groups(too_small)}) hold fewer than "
            f"{MIN_TESTABLE_GROUP_N} values and were excluded from the significance test, "
            f"removing {len(subset) - tested_rows} row(s) from its denominator. They remain "
            f"in the summary table."
        )
    n = tested_rows if ran_a_test else len(subset)
    return frame_to_result(
        summary,
        op="group_comparison",
        label=label,
        n=n,
        n_excluded=len(df) - n,
        notes=notes,
        stats_payload=stats_payload,
    )


# Tier 1 and Tier 2 live here; every heavier tier is registered from the module
# that implements it, so this table stays the single place a spec's "op" is
# resolved.
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
    **INFERENCE_OPERATIONS,
    **CATEGORICAL_OPERATIONS,
    **REGRESSION_OPERATIONS,
    **TIMESERIES_OPERATIONS,
    **SURVEY_OPERATIONS,
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
        # Stamped here rather than inside each handler: the handlers do not
        # know their position in the plan, and this list is about to stop
        # matching it as soon as anything fails.
        results.append(with_spec_index(result, index))

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
    # Tier 3 result tables lead with the group label and n, so column 1 is a
    # sample size. Charting that under a title about means or rates is the bug
    # this map exists to prevent.
    "ttest": "mean",
    "anova": "mean",
    "kruskal": "median",
    "mannwhitney": "median",
    "wilcoxon": "median",
    "proportion_test": "proportion",
    "chi_square": "observed",
    "normality_test": "mean",
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
    if not isinstance(index, int):
        return None

    # ``chart["operation"]`` names a position in the *spec*, and execute_spec
    # drops failures from *results*. Indexing the list positionally therefore
    # plots a different operation than the one the chart config asked for
    # whenever anything earlier failed — a chart titled for one analysis
    # carrying another's numbers.
    result = next((entry for entry in results if entry.planned_at(index)), None)
    if result is None:
        return None
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
