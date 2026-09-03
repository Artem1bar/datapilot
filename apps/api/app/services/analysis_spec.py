"""Analysis operation whitelist and spec validation.

The analysis pipeline mirrors the cleaning pipeline's trust model: the model
proposes a *plan*, the plan is validated against a fixed operation set and the
dataset's real columns, and only then does deterministic code execute it. The
model never supplies a value — it chooses what to compute and later explains
what the computed numbers mean.

This module owns step 2 of that pipeline (validate). Execution lives in
:mod:`app.services.analysis_executor` and, for the inferential tests, in
:mod:`app.services.analysis_inference` and
:mod:`app.services.analysis_categorical`; orchestration in
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
dataset, a numeric aggregation over a text column, or a filter on a category
that does not occur is rejected rather than coerced. A rejected spec is fed back
to the model with the specific failures, the same regenerate-on-rejection loop
the cleaning planner uses.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.analysis_registry import (  # noqa: F401  (re-exported for callers)
    Check,
    ColumnRoles,
    OperationDef,
    Param,
    SpecError,
)
from app.services.analysis_regression import REGRESSION_OPERATION_DEFS
from app.services.analysis_survey import SURVEY_OPERATION_DEFS
from app.services.analysis_timeseries import TIMESERIES_OPERATION_DEFS

# Aggregations usable wherever an ``agg`` parameter appears.
NUMERIC_AGGS = frozenset({"sum", "mean", "median", "min", "max", "std", "var"})
UNIVERSAL_AGGS = frozenset({"count", "nunique"})
ALL_AGGS = NUMERIC_AGGS | UNIVERSAL_AGGS

CORRELATION_METHODS = frozenset({"pearson", "spearman", "kendall"})

FILTER_OPERATORS = frozenset(
    {"==", "!=", ">", ">=", "<", "<=", "contains", "not_contains", "is_null", "is_not_null"}
)

CHART_TYPES = frozenset({"bar", "line", "scatter", "bubble", "pie", "histogram"})

# How many colors a scatter legend can hold. Past this a color-by column is an
# identifier rather than a grouping, and the chart is unreadable rather than
# wrong — so it is refused, not drawn.
MAX_SCATTER_GROUPS = 12

# Time-series resample frequencies, restricted to an unambiguous set rather than
# accepting arbitrary pandas offset aliases from a model.
RESAMPLE_FREQS = frozenset({"D", "W", "ME", "QE", "YE"})

# ---------------------------------------------------------------------------
# Operation registry
# ---------------------------------------------------------------------------


def _check_ttest(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    kind = params.get("kind")
    needed = {"one_sample": "mu", "independent": "group_by", "paired": "column2"}.get(str(kind))
    problems: list[str] = []
    if needed and needed not in params:
        problems.append(f"ttest: kind {kind!r} requires parameter {needed!r}")
    # A parameter that belongs to a different kind would be silently dropped at
    # execution, which reads as the test having used it.
    for parameter in {"mu", "group_by", "column2"} - {needed}:
        if parameter in params:
            problems.append(
                f"ttest: parameter {parameter!r} does not apply to kind {kind!r} and would be ignored"
            )
    return problems


def _check_chi_square(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    kind = params.get("kind")
    if kind == "independence" and "row" not in params:
        return ["chi_square: a test of independence requires 'row'"]
    if kind == "goodness_of_fit" and "row" in params:
        return ["chi_square: a goodness-of-fit test takes one column; drop 'row'"]
    return []


def _check_proportion_test(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    problems: list[str] = []
    grouped = "group_by" in params
    if grouped and "p0" in params:
        return [
            "proportion_test: give either 'group_by' (compare two groups) or 'p0' "
            "(compare against a hypothesized proportion), not both"
        ]
    if not grouped and "p0" not in params:
        problems.append(
            "proportion_test: without 'group_by' this compares one proportion against a "
            "hypothesized value, so 'p0' is required"
        )

    # success_value names a category of the outcome column; check it against
    # the real values so a case or spelling mismatch is caught before execution
    # rather than surfacing as a proportion of zero.
    column, success = params.get("column"), params.get("success_value")
    known = roles.categories.get(str(column)) if isinstance(column, str) else None
    if known and success is not None and str(success) not in known:
        problems.append(
            f"proportion_test: success_value {success!r} does not occur in {column!r} "
            f"(values: {sorted(known)[:20]})"
        )
    return problems


def _check_scatter(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    x, y = params.get("x"), params.get("y")
    size, color_by = params.get("size"), params.get("color_by")
    if x == y:
        return [f"x and y are the same column {x!r}; a scatter needs two"]
    if isinstance(size, str) and size in (x, y):
        return [f"size: {size!r} is already an axis; choose a different column"]
    if not isinstance(color_by, str):
        return []
    if color_by in (x, y):
        return [f"color_by: {color_by!r} is already an axis; choose a different column"]
    if color_by == size:
        return [f"color_by: {color_by!r} is also the size column; choose a different column"]
    if color_by in roles.datetime:
        return [f"color_by: {color_by!r} is a date/time column; choose a categorical column"]
    known = roles.categories.get(color_by)
    if known is not None and len(known) > MAX_SCATTER_GROUPS:
        return [
            f"color_by: {color_by!r} has {len(known)} distinct values; "
            f"at most {MAX_SCATTER_GROUPS} can be colored"
        ]
    return []


OPERATIONS: dict[str, OperationDef] = {
    # ---- Tier 1: descriptive & aggregation ----
    "describe": OperationDef(
        1,
        "Summary statistics (count, mean, sd, quartiles) for numeric columns.",
        (Param("columns", "columns"),),
    ),
    "groupby_aggregate": OperationDef(
        1,
        "One aggregate of a column, per group.",
        (
            Param("group_by", "columns", required=True),
            Param("column", "column", required=True),
            Param("agg", "agg", required=True),
        ),
    ),
    "value_counts": OperationDef(
        1,
        "How often each value of a column occurs.",
        (
            Param("column", "column", required=True),
            Param("top_n", "int"),
            Param("normalize", "bool"),
        ),
    ),
    "crosstab": OperationDef(
        1,
        "Counts of one column against another, with a chi-square test of independence.",
        (
            Param("row", "column", required=True),
            Param("column", "column", required=True),
            Param("normalize", "bool"),
        ),
    ),
    "histogram": OperationDef(
        1,
        "The distribution of a numeric column, as binned counts.",
        (Param("column", "numeric", required=True), Param("bins", "int")),
    ),
    "top_n": OperationDef(
        1,
        "The highest (or lowest) rows by a numeric column.",
        (
            Param("column", "column", required=True),
            Param("by", "numeric", required=True),
            Param("n", "int"),
            Param("ascending", "bool"),
        ),
    ),
    "pivot": OperationDef(
        1,
        "A two-dimensional aggregate table.",
        (
            Param("index", "columns", required=True),
            Param("columns", "column", required=True),
            Param("values", "numeric", required=True),
            Param("agg", "agg", required=True),
        ),
    ),
    "resample": OperationDef(
        1,
        "A numeric column rolled up over time.",
        (
            Param("date_column", "datetime", required=True),
            Param("column", "numeric", required=True),
            Param("freq", "freq", required=True),
            Param("agg", "agg", required=True),
        ),
    ),
    # ---- Tier 2: bivariate ----
    "correlation_matrix": OperationDef(
        2,
        "Pairwise correlations between numeric columns, with p-values.",
        (Param("columns", "numerics", required=True), Param("method", "method")),
    ),
    "scatter_with_fit": OperationDef(
        2,
        "Two numeric columns with an OLS line: slope, R-squared, p-value. "
        "A numeric size makes it a bubble chart.",
        (
            Param("x", "numeric", required=True),
            Param("y", "numeric", required=True),
            Param("size", "numeric"),
            Param("color_by", "column"),
        ),
        requires=(
            "size, when given, is a numeric column other than x and y; color_by, when "
            f"given, is a categorical column with at most {MAX_SCATTER_GROUPS} distinct "
            "values (a missing label does not count), and is neither x, y nor size"
        ),
        check=_check_scatter,
    ),
    "group_comparison": OperationDef(
        2,
        "Means with 95% intervals per group, plus a significance test.",
        (
            Param("group_by", "column", required=True),
            Param("column", "numeric", required=True),
        ),
    ),
    # ---- Tier 3: inferential ----
    "ttest": OperationDef(
        3,
        "Test a mean: against a fixed value, between two groups, or within pairs. "
        "Reports Cohen's d, a confidence interval, and normality/variance checks.",
        (
            Param("kind", "choice", required=True, choices=("one_sample", "independent", "paired")),
            Param("column", "numeric", required=True),
            Param("group_by", "column"),
            Param("column2", "numeric"),
            Param("mu", "number"),
            Param("alternative", "choice", choices=("two-sided", "less", "greater")),
            Param("equal_var", "bool"),
        ),
        requires=(
            "kind=one_sample needs 'mu'; kind=independent needs 'group_by' (exactly two "
            "groups); kind=paired needs 'column2'. Welch's test is the default — set "
            "equal_var only when the groups are known to have equal variance."
        ),
        check=_check_ttest,
    ),
    "anova": OperationDef(
        3,
        "Compare means across three or more groups. Reports F, eta squared, "
        "Levene's and normality checks, and Tukey HSD pairwise comparisons.",
        (
            Param("group_by", "column", required=True),
            Param("column", "numeric", required=True),
        ),
    ),
    "kruskal": OperationDef(
        3,
        "Rank-based alternative to anova: no normality assumption. "
        "Use when groups are small, skewed, or contain outliers.",
        (
            Param("group_by", "column", required=True),
            Param("column", "numeric", required=True),
        ),
    ),
    "mannwhitney": OperationDef(
        3,
        "Rank-based alternative to a two-group ttest. Reports rank-biserial "
        "correlation and the Hodges-Lehmann shift.",
        (
            Param("group_by", "column", required=True),
            Param("column", "numeric", required=True),
            Param("alternative", "choice", choices=("two-sided", "less", "greater")),
        ),
    ),
    "wilcoxon": OperationDef(
        3,
        "Rank-based alternative to a paired ttest, over two columns of the same rows.",
        (
            Param("column", "numeric", required=True),
            Param("column2", "numeric", required=True),
            Param("alternative", "choice", choices=("two-sided", "less", "greater")),
        ),
    ),
    "chi_square": OperationDef(
        3,
        "Test categorical association (independence) or whether one column's "
        "categories are evenly distributed (goodness_of_fit). Reports Cramér's V "
        "and checks expected cell counts.",
        (
            Param("kind", "choice", required=True, choices=("independence", "goodness_of_fit")),
            Param("column", "column", required=True),
            Param("row", "column"),
        ),
        requires=(
            "kind=independence needs 'row' as well as 'column'; kind=goodness_of_fit "
            "takes 'column' alone and tests it against an even split."
        ),
        check=_check_chi_square,
    ),
    "proportion_test": OperationDef(
        3,
        "Test a rate: between two groups, or against a hypothesized proportion. "
        "Reports Wilson intervals and Cohen's h.",
        (
            Param("column", "column", required=True),
            Param("success_value", "value", required=True),
            Param("group_by", "column"),
            Param("p0", "proportion"),
        ),
        requires=(
            "give 'group_by' to compare two groups, or 'p0' to test against a "
            "hypothesized proportion — one or the other, never both. success_value is "
            "the category that counts as a success, spelled exactly as it appears."
        ),
        check=_check_proportion_test,
    ),
    "normality_test": OperationDef(
        3,
        "Whether a numeric column is plausibly normal — the check behind choosing "
        "a t-test over a rank-based test.",
        (Param("column", "numeric", required=True), Param("group_by", "column")),
    ),
    # Tiers 4-6 declare themselves in the modules that execute them, so adding
    # a tier means adding one file rather than editing the registry, the
    # dispatch table and the prompt separately.
    **REGRESSION_OPERATION_DEFS,
    **TIMESERIES_OPERATION_DEFS,
    **SURVEY_OPERATION_DEFS,
}


def tier_operations(tier: int) -> frozenset[str]:
    """Operation names belonging to *tier*."""
    return frozenset(name for name, definition in OPERATIONS.items() if definition.tier == tier)


TIER_1 = tier_operations(1)
TIER_2 = tier_operations(2)
TIER_3 = tier_operations(3)
TIER_4 = tier_operations(4)
TIER_5 = tier_operations(5)
TIER_6 = tier_operations(6)

# Cap on operations per spec — a question needing more than this is better
# answered as several questions, and it bounds execution time.
MAX_OPERATIONS = 6


def _check_column(name: Any, roles: ColumnRoles, *, where: str) -> list[str]:
    if not isinstance(name, str) or not name:
        return [f"{where}: expected a column name, got {name!r}"]
    if name not in roles.all:
        return [f"{where}: column {name!r} is not in the dataset"]
    return []


def _validate_param(param: Param, value: Any, roles: ColumnRoles, *, where: str) -> list[str]:
    """Return a list of problems with one parameter value (empty when valid)."""
    kind = param.kind

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

    if kind == "choice":
        if value not in param.choices:
            return [f"{where}: expected one of {list(param.choices)}, got {value!r}"]
        return []

    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return [f"{where}: expected a positive integer, got {value!r}"]
        return []

    if kind == "count":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return [f"{where}: expected a non-negative integer, got {value!r}"]
        return []

    if kind == "text":
        if not isinstance(value, str) or not value.strip():
            return [f"{where}: expected a non-empty string, got {value!r}"]
        return []

    if kind == "bool":
        if not isinstance(value, bool):
            return [f"{where}: expected true or false, got {value!r}"]
        return []

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{where}: expected a number, got {value!r}"]
        return []

    if kind == "proportion":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{where}: expected a number between 0 and 1, got {value!r}"]
        if not 0 < float(value) < 1:
            return [f"{where}: expected a proportion strictly between 0 and 1, got {value!r}"]
        return []

    if kind == "value":
        if value is None or isinstance(value, (list, dict)):
            return [f"{where}: expected a single value from the data, got {value!r}"]
        return []

    return [f"{where}: unknown parameter kind {kind!r}"]  # pragma: no cover - registry bug


def _validate_operation(index: int, operation: Any, roles: ColumnRoles) -> list[str]:
    where = f"operations[{index}]"
    if not isinstance(operation, dict):
        return [f"{where}: expected an object, got {type(operation).__name__}"]

    op = operation.get("op")
    definition = OPERATIONS.get(op) if isinstance(op, str) else None
    if definition is None:
        return [f"{where}: unknown operation {op!r} (allowed: {sorted(OPERATIONS)})"]

    params = operation.get("params")
    if not isinstance(params, dict):
        return [f"{where}: 'params' must be an object"]

    problems: list[str] = []
    known = {param.name for param in definition.params}

    for param in definition.params:
        if param.name not in params:
            if param.required:
                problems.append(f"{where}: {op} requires parameter {param.name!r}")
            continue
        problems += _validate_param(param, params[param.name], roles, where=f"{where}.{param.name}")

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

    # Conditional requirements run last, and only on a spec whose individual
    # parameters are already sound — otherwise they report on values the
    # earlier checks have already rejected.
    if definition.check is not None and not problems:
        problems += [f"{where}: {problem}" for problem in definition.check(params, roles)]

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

    # An equality filter on a value that does not occur silently yields an empty
    # frame, and every operation downstream then fails for reasons that have
    # nothing to do with the question. Catch the typo here instead.
    column, value = spec_filter.get("column"), spec_filter.get("value")
    known = roles.categories.get(str(column)) if isinstance(column, str) else None
    if operator == "==" and known and value is not None and str(value) not in known:
        problems.append(f"filter: {column!r} has no value {value!r} (values: {sorted(known)[:20]})")
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
    for name, definition in OPERATIONS.items():
        lines.append(f"- {name} [tier {definition.tier}] — {definition.summary}")
        rendered = " · ".join(param.render() for param in definition.params)
        lines.append(f"    params: {rendered or 'none'}")
        if definition.requires:
            lines.append(f"    rules: {definition.requires}")
    return "\n".join(lines)


Aggregation = Literal["sum", "mean", "median", "min", "max", "std", "var", "count", "nunique"]
