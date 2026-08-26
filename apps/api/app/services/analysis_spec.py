"""Analysis operation whitelist and spec validation.

The analysis pipeline mirrors the cleaning pipeline's trust model: the model
proposes a *plan*, the plan is validated against a fixed operation set and the
dataset's real columns, and only then does deterministic code execute it. The
model never supplies a value — it chooses what to compute and later explains
what the computed numbers mean.

This module owns step 2 of that pipeline (validate). Execution lives in
:mod:`app.services.analysis_executor`; orchestration in
:mod:`app.services.analysis`.

An ``AnalysisSpec`` is::

    {
      "rationale": "why these operations answer the question",
      "filter": {"column": "region", "operator": "==", "value": "West"} | null,
      "operations": [
        {"op": "groupby_aggregate",
         "label": "Total revenue by region",
         "params": {"group_by": ["region"], "column": "revenue", "agg": "sum"}},
      ],
      "chart": {"type": "bar", "operation": 0} | null
    }

Validation is deliberately strict: an unknown op, a column that is not in the
dataset, or a numeric aggregation over a text column is rejected rather than
coerced. A rejected spec is fed back to the model with the specific failures,
the same regenerate-on-rejection loop the cleaning planner uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

# Aggregations usable wherever an ``agg`` parameter appears.
NUMERIC_AGGS = frozenset({"sum", "mean", "median", "min", "max", "std", "var"})
UNIVERSAL_AGGS = frozenset({"count", "nunique"})
ALL_AGGS = NUMERIC_AGGS | UNIVERSAL_AGGS

CORRELATION_METHODS = frozenset({"pearson", "spearman", "kendall"})

FILTER_OPERATORS = frozenset(
    {"==", "!=", ">", ">=", "<", "<=", "contains", "not_contains", "is_null", "is_not_null"}
)

CHART_TYPES = frozenset({"bar", "line", "scatter", "pie", "histogram"})

# Time-series resample frequencies, restricted to an unambiguous set rather than
# accepting arbitrary pandas offset aliases from a model.
RESAMPLE_FREQS = frozenset({"D", "W", "ME", "QE", "YE"})


@dataclass(frozen=True)
class ColumnRoles:
    """Which columns exist and what may be done with them.

    Built from the dataframe itself rather than the stored profile, so
    validation always reflects the file being analyzed.
    """

    all: frozenset[str]
    numeric: frozenset[str]
    datetime: frozenset[str]

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> ColumnRoles:
        return cls(
            all=frozenset(str(c) for c in df.columns),
            numeric=frozenset(str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])),
            datetime=frozenset(
                str(c) for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])
            ),
        )


class SpecError(ValueError):
    """The model's analysis spec could not be validated."""


# ---------------------------------------------------------------------------
# Operation registry
# ---------------------------------------------------------------------------
#
# Each entry declares its parameters as (name, kind, required) where kind is:
#   "column"      — a single column that must exist
#   "columns"     — a non-empty list of columns that must exist
#   "numeric"     — a single column that must exist and be numeric
#   "numerics"    — a non-empty list of existing numeric columns
#   "datetime"    — a single column that must exist and be datetime-typed
#   "agg"         — a member of ALL_AGGS
#   "int"         — a positive integer
#   "bool"        — a boolean
#   "method"      — a member of CORRELATION_METHODS
#   "freq"        — a member of RESAMPLE_FREQS

_ParamSpec = tuple[str, str, bool]

OPERATIONS: dict[str, tuple[_ParamSpec, ...]] = {
    # ---- Tier 1: descriptive & aggregation ----
    "describe": (("columns", "columns", False),),
    "groupby_aggregate": (
        ("group_by", "columns", True),
        ("column", "column", True),
        ("agg", "agg", True),
    ),
    "value_counts": (
        ("column", "column", True),
        ("top_n", "int", False),
        ("normalize", "bool", False),
    ),
    "crosstab": (
        ("row", "column", True),
        ("column", "column", True),
        ("normalize", "bool", False),
    ),
    "histogram": (("column", "numeric", True), ("bins", "int", False)),
    "top_n": (
        ("column", "column", True),
        ("by", "numeric", True),
        ("n", "int", False),
        ("ascending", "bool", False),
    ),
    "pivot": (
        ("index", "columns", True),
        ("columns", "column", True),
        ("values", "numeric", True),
        ("agg", "agg", True),
    ),
    "resample": (
        ("date_column", "datetime", True),
        ("column", "numeric", True),
        ("freq", "freq", True),
        ("agg", "agg", True),
    ),
    # ---- Tier 2: bivariate ----
    "correlation_matrix": (
        ("columns", "numerics", True),
        ("method", "method", False),
    ),
    "scatter_with_fit": (("x", "numeric", True), ("y", "numeric", True)),
    "group_comparison": (("group_by", "column", True), ("column", "numeric", True)),
}

TIER_1 = frozenset(
    {
        "describe",
        "groupby_aggregate",
        "value_counts",
        "crosstab",
        "histogram",
        "top_n",
        "pivot",
        "resample",
    }
)
TIER_2 = frozenset({"correlation_matrix", "scatter_with_fit", "group_comparison"})

# Cap on operations per spec — a question needing more than this is better
# answered as several questions, and it bounds execution time.
MAX_OPERATIONS = 6


def _check_column(name: Any, roles: ColumnRoles, *, where: str) -> list[str]:
    if not isinstance(name, str) or not name:
        return [f"{where}: expected a column name, got {name!r}"]
    if name not in roles.all:
        return [f"{where}: column {name!r} is not in the dataset"]
    return []


def _validate_param(kind: str, value: Any, roles: ColumnRoles, *, where: str) -> list[str]:
    """Return a list of problems with one parameter value (empty when valid)."""
    if kind == "column":
        return _check_column(value, roles, where=where)

    if kind in ("columns", "numerics"):
        if not isinstance(value, list) or not value:
            return [f"{where}: expected a non-empty list of columns, got {value!r}"]
        problems: list[str] = []
        for item in value:
            problems += _check_column(item, roles, where=where)
            if not problems and kind == "numerics" and item not in roles.numeric:
                problems.append(f"{where}: column {item!r} is not numeric")
        return problems

    if kind == "numeric":
        problems = _check_column(value, roles, where=where)
        if problems:
            return problems
        if value not in roles.numeric:
            return [f"{where}: column {value!r} is not numeric"]
        return []

    if kind == "datetime":
        problems = _check_column(value, roles, where=where)
        if problems:
            return problems
        if value not in roles.datetime:
            return [
                f"{where}: column {value!r} is not a date/time column "
                f"(available: {sorted(roles.datetime) or 'none'})"
            ]
        return []

    if kind == "agg":
        if value not in ALL_AGGS:
            return [f"{where}: unknown aggregation {value!r} (allowed: {sorted(ALL_AGGS)})"]
        return []

    if kind == "method":
        if value not in CORRELATION_METHODS:
            return [f"{where}: unknown method {value!r} (allowed: {sorted(CORRELATION_METHODS)})"]
        return []

    if kind == "freq":
        if value not in RESAMPLE_FREQS:
            return [f"{where}: unknown frequency {value!r} (allowed: {sorted(RESAMPLE_FREQS)})"]
        return []

    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return [f"{where}: expected a positive integer, got {value!r}"]
        return []

    if kind == "bool":
        if not isinstance(value, bool):
            return [f"{where}: expected true or false, got {value!r}"]
        return []

    return [f"{where}: unknown parameter kind {kind!r}"]  # pragma: no cover - registry bug


def _validate_operation(index: int, operation: Any, roles: ColumnRoles) -> list[str]:
    where = f"operations[{index}]"
    if not isinstance(operation, dict):
        return [f"{where}: expected an object, got {type(operation).__name__}"]

    op = operation.get("op")
    if op not in OPERATIONS:
        return [f"{where}: unknown operation {op!r} (allowed: {sorted(OPERATIONS)})"]

    params = operation.get("params")
    if not isinstance(params, dict):
        return [f"{where}: 'params' must be an object"]

    problems: list[str] = []
    declared = OPERATIONS[op]
    known = {name for name, _, _ in declared}

    for name, kind, required in declared:
        if name not in params:
            if required:
                problems.append(f"{where}: {op} requires parameter {name!r}")
            continue
        problems += _validate_param(kind, params[name], roles, where=f"{where}.{name}")

    for extra in set(params) - known:
        problems.append(f"{where}: {op} does not accept parameter {extra!r}")

    # A numeric aggregation over a non-numeric column silently produces garbage
    # (or raises deep inside pandas), so reject the combination up front.
    agg = params.get("agg")
    target = params.get("column") if op != "pivot" else params.get("values")
    if (
        agg in NUMERIC_AGGS
        and isinstance(target, str)
        and target in roles.all
        and target not in roles.numeric
    ):
        problems.append(
            f"{where}: aggregation {agg!r} needs a numeric column, but {target!r} is not numeric "
            f"(use 'count' or 'nunique' instead)"
        )

    return problems


def _validate_filter(spec_filter: Any, roles: ColumnRoles) -> list[str]:
    if spec_filter is None:
        return []
    if not isinstance(spec_filter, dict):
        return ["filter: expected an object or null"]

    problems = _check_column(spec_filter.get("column"), roles, where="filter.column")
    operator = spec_filter.get("operator")
    if operator not in FILTER_OPERATORS:
        problems.append(
            f"filter.operator: unknown operator {operator!r} (allowed: {sorted(FILTER_OPERATORS)})"
        )
    if operator not in ("is_null", "is_not_null") and "value" not in spec_filter:
        problems.append(f"filter: operator {operator!r} requires a 'value'")
    return problems


def _validate_chart(chart: Any, operation_count: int) -> list[str]:
    if chart is None:
        return []
    if not isinstance(chart, dict):
        return ["chart: expected an object or null"]

    problems: list[str] = []
    chart_type = chart.get("type")
    if chart_type not in CHART_TYPES:
        problems.append(f"chart.type: unknown type {chart_type!r} (allowed: {sorted(CHART_TYPES)})")

    index = chart.get("operation")
    if not isinstance(index, int) or isinstance(index, bool):
        problems.append(f"chart.operation: expected an operation index, got {index!r}")
    elif not 0 <= index < operation_count:
        problems.append(
            f"chart.operation: index {index} is out of range "
            f"(spec has {operation_count} operation(s))"
        )

    # 'y' names a column of the RESULT table, which does not exist until the
    # operation runs, so it cannot be checked here — only its type. An unknown
    # name falls back to the per-operation default at chart-build time.
    if "y" in chart and not isinstance(chart["y"], str):
        problems.append(f"chart.y: expected a result column name, got {chart['y']!r}")
    return problems


def validate_spec(spec: Any, roles: ColumnRoles) -> list[str]:
    """Return every problem with *spec*; an empty list means it is safe to execute.

    All problems are collected rather than raising on the first, so a rejected
    spec can be regenerated in one round trip instead of one per mistake.
    """
    if not isinstance(spec, dict):
        return [f"spec: expected an object, got {type(spec).__name__}"]

    # A spec that declines to answer is valid and terminal — the model saying
    # "this data cannot answer that" is a feature, not a failure.
    if spec.get("refusal"):
        return []

    operations = spec.get("operations")
    if not isinstance(operations, list) or not operations:
        return ["operations: expected a non-empty list (or set 'refusal' to decline)"]
    if len(operations) > MAX_OPERATIONS:
        return [
            f"operations: at most {MAX_OPERATIONS} operations per question, got {len(operations)}"
        ]

    problems: list[str] = []
    problems += _validate_filter(spec.get("filter"), roles)
    for index, operation in enumerate(operations):
        problems += _validate_operation(index, operation, roles)
    problems += _validate_chart(spec.get("chart"), len(operations))
    return problems


def describe_capabilities() -> str:
    """Render the operation registry as prompt text.

    Generated from ``OPERATIONS`` so the planner prompt cannot drift from what
    the validator actually accepts — the usual failure mode for a hand-written
    list of allowed operations.
    """
    lines: list[str] = []
    for op, params in OPERATIONS.items():
        tier = "1" if op in TIER_1 else "2"
        rendered = ", ".join(
            f"{name}: {kind}{'' if required else ' (optional)'}" for name, kind, required in params
        )
        lines.append(f"- {op} [tier {tier}] — {rendered or 'no parameters'}")
    return "\n".join(lines)


Aggregation = Literal["sum", "mean", "median", "min", "max", "std", "var", "count", "nunique"]
