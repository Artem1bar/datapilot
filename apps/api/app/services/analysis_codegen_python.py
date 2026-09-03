"""Python source for a validated analysis spec — the export half of the trust bridge.

Step 3 of the analysis pipeline computes every number the user sees. This module
writes the script that computes them again, somewhere else, in the researcher's
own environment. That is the only way a claim of correctness becomes checkable
rather than merely asserted: run the export against the same file and the
numbers must be identical, not merely similar.

Two rules govern everything here.

**Nothing but a literal.** Column names and category values come from user data.
They contain quotes, backslashes, newlines and characters that are not valid
identifiers, and a name interpolated raw into source is at best a syntax error
and at worst arbitrary code. Every value crossing into emitted source goes
through :func:`py_literal`; there is no other route. Labels reaching a comment
go through :func:`comment_text`, which folds them onto one line.

**The export is a transcript, not a reimplementation.** Where the executor
writes ``series.value_counts(normalize=False, dropna=True)``, so does the
export — including the parts a reimplementation would tidy up, because a tidier
script that returns a different number defeats the purpose.

Adding an operation means registering one emitter::

    from app.services.analysis_codegen_python import PYTHON_EMITTERS, py_literal

    def _emit_ols(params, label, index):
        return [f"result_{index} = smf.ols({py_literal(params['formula'])}, data=d).fit()"]

    PYTHON_EMITTERS["ols"] = _emit_ols

An operation with no emitter is not silently dropped; the façade in
:mod:`app.services.analysis_codegen` emits a comment saying so.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable, Sequence
from typing import Any

from app.services.analysis_result import MISSING_GROUP_LABEL

Lines = list[str]

# (params, label, position) -> lines of Python. ``position`` is the operation's
# 1-based index in the spec, and names the variables the block assigns.
Emitter = Callable[[dict[str, Any], str, int], Lines]

# The variable the load line assigns, and the frame after the spec's filter.
FRAME = "df"
DATA = "d"

# Defaults for optional parameters. These mirror analysis_executor's constants;
# a test asserts they have not drifted, because a different default is a
# different number.
DEFAULT_TOP_N = 10
DEFAULT_VALUE_COUNTS = 20
DEFAULT_BINS = 10

# Mirrors analysis_inference.MAX_HODGES_LEHMANN_PAIRS.
MAX_HODGES_LEHMANN_PAIRS = 4_000_000

# Mirrors analysis_stats.CONFIDENCE_LEVEL and ALPHA.
CONFIDENCE_LEVEL = 0.95
ALPHA = 0.05


# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------


def py_literal(value: Any) -> str:
    """Render *value* as Python source.

    The only sanctioned way for data to enter emitted code. ``repr`` does the
    work for the types that reach here from a validated spec; the special cases
    are the ones ``repr`` gets wrong as *source*: ``nan`` and ``inf`` render as
    bare names that would raise ``NameError``, and a numpy scalar renders as a
    constructor call that assumes numpy is imported under a particular alias.
    """
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, numbers.Integral):
        return repr(int(value))
    if isinstance(value, numbers.Real):
        as_float = float(value)
        if math.isnan(as_float):
            return "float('nan')"
        if math.isinf(as_float):
            return "float('inf')" if as_float > 0 else "float('-inf')"
        return repr(as_float)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(py_literal(item) for item in value) + "]"
    return repr(str(value))


def comment_text(text: Any) -> str:
    """Fold a user-supplied string onto one line, so it cannot escape a comment."""
    return " ".join(str(text).split())


def python_load_statement(source: str) -> str:
    """The single statement that loads the data.

    Kept to one line on purpose: it is the one line a reader edits to point at
    their own file, and the one line a caller substitutes to run the export
    against a frame it already has.
    """
    return f"{FRAME} = pd.read_csv({py_literal(source)})"


def _q(params: dict[str, Any], key: str) -> str:
    """The literal for one parameter."""
    return py_literal(params[key])


# ---------------------------------------------------------------------------
# Helpers emitted into the script
# ---------------------------------------------------------------------------
#
# Emitted only when an operation needs them, so a script for a value count does
# not carry group-splitting code it never calls. Each emitter declares what it
# needs through :func:`_emits`.

_HELPERS: dict[str, str] = {
    "show": '''def show(title, frame=None, values=None):
    """Print one operation's result the way the product displays it."""
    print("\\n=== " + title + " ===")
    if frame is not None:
        print(frame.to_string(index=False))
    for key, value in (values or {}).items():
        print("  {}: {}".format(key, value))''',
    "split_groups": '''def split_groups(frame, group_column, value_column):
    """Groups in sorted label order, dropping rows missing either column.

    Sorted order is what makes the sign of a reported difference stable: it is
    "alphabetically first minus second", not "whichever row came first in the
    upload".
    """
    pair = pd.DataFrame({
        "group": frame[group_column],
        "value": pd.to_numeric(frame[value_column], errors="coerce"),
    }).dropna()
    labels = sorted(str(value) for value in pair["group"].unique())
    groups = [
        pair.loc[pair["group"].astype(str) == label, "value"].to_numpy(dtype=float)
        for label in labels
    ]
    return labels, groups''',
    "mean_ci": '''def mean_ci(values, level=__LEVEL__):
    """Two-sided t interval for a sample mean."""
    values = np.asarray(values, dtype=float)
    if values.size < 2:
        return float("nan"), float("nan")
    sd = float(values.std(ddof=1))
    mean = float(values.mean())
    if sd <= 0:
        return mean, mean
    margin = float(stats.t.ppf(1 - (1 - level) / 2, values.size - 1)) * sd / math.sqrt(values.size)
    return mean - margin, mean + margin''',
    "mean_difference_ci": '''def mean_difference_ci(a, b, equal_var=False, level=__LEVEL__):
    """Interval for a difference in means, matching the t-test that was run."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n1, n2 = a.size, b.size
    var1, var2 = a.var(ddof=1), b.var(ddof=1)
    if equal_var:
        pooled = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        standard_error = math.sqrt(pooled * (1 / n1 + 1 / n2))
        dof = float(n1 + n2 - 2)
    else:
        standard_error = math.sqrt(var1 / n1 + var2 / n2)
        dof = (var1 / n1 + var2 / n2) ** 2 / (
            (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        )
    difference = float(a.mean() - b.mean())
    margin = float(stats.t.ppf(1 - (1 - level) / 2, dof)) * standard_error
    return difference - margin, difference + margin''',
    "cohens_d": '''def cohens_d(a, b):
    """Standardized mean difference, and Hedges' g (the small-sample correction)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n1, n2 = a.size, b.size
    pooled = ((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2)
    if pooled <= 0:
        return float("nan"), float("nan")
    d = float((a.mean() - b.mean()) / math.sqrt(pooled))
    return d, d * (1 - 3 / (4 * (n1 + n2) - 9))''',
    "group_summary": '''def group_summary(labels, groups, group_column):
    """Per-group means with 95% intervals — the table behind a mean comparison."""
    rows = []
    for label, values in zip(labels, groups):
        low, high = mean_ci(values)
        rows.append({
            group_column: label,
            "n": int(values.size),
            "mean": float(values.mean()),
            "sd": float(values.std(ddof=1)) if values.size > 1 else None,
            "median": float(np.median(values)),
            "ci95_low": low,
            "ci95_high": high,
        })
    return pd.DataFrame(rows)''',
    "rank_summary": '''def rank_summary(labels, groups, group_column):
    """Per-group medians and mean ranks — the table behind a rank-based test."""
    ranks = stats.rankdata(np.concatenate(groups))
    rows, offset = [], 0
    for label, values in zip(labels, groups):
        block = ranks[offset:offset + values.size]
        offset += values.size
        rows.append({
            group_column: label,
            "n": int(values.size),
            "median": float(np.median(values)),
            "q1": float(np.percentile(values, 25)),
            "q3": float(np.percentile(values, 75)),
            "mean_rank": float(block.mean()),
        })
    return pd.DataFrame(rows)''',
    "normality_p": '''def normality_p(values):
    """Shapiro-Wilk, or D'Agostino K-squared past 5,000 observations.

    Shapiro-Wilk is defined for 3 <= n <= 5000; beyond that its p-value is not
    reliable, which is why the product switches test rather than reporting one
    out of range.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 3 or float(np.std(values)) == 0.0:
        return float("nan")
    if values.size <= 5000:
        return float(stats.shapiro(values).pvalue)
    return float(stats.normaltest(values).pvalue)''',
    "wilson_ci": '''def wilson_ci(successes, n, level=__LEVEL__):
    """Wilson score interval for a proportion.

    Preferred over the normal approximation, which runs past 0 and 1 and
    collapses to zero width at p = 0 — exactly where an honest interval matters.
    """
    z = float(stats.norm.ppf(1 - (1 - level) / 2))
    p = successes / n
    denominator = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denominator
    margin = (z / denominator) * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return max(0.0, center - margin), min(1.0, center + margin)''',
    "proportion_difference_ci": '''def proportion_difference_ci(successes1, n1, successes2, n2):
    """Newcombe's interval, built from the two Wilson intervals."""
    low1, high1 = wilson_ci(successes1, n1)
    low2, high2 = wilson_ci(successes2, n2)
    p1, p2 = successes1 / n1, successes2 / n2
    difference = p1 - p2
    lower = difference - math.sqrt((p1 - low1) ** 2 + (high2 - p2) ** 2)
    upper = difference + math.sqrt((high1 - p1) ** 2 + (p2 - low2) ** 2)
    return max(-1.0, lower), min(1.0, upper)''',
}

# Helpers that call other helpers.
_HELPER_REQUIRES: dict[str, tuple[str, ...]] = {
    "group_summary": ("mean_ci",),
    "proportion_difference_ci": ("wilson_ci",),
}


# Substituted rather than %-formatted: helper docstrings contain "95%".
_LEVEL_TOKEN = "__LEVEL__"


def _helper_source(name: str) -> str:
    return _HELPERS[name].replace(_LEVEL_TOKEN, repr(CONFIDENCE_LEVEL))


PYTHON_EMITTERS: dict[str, Emitter] = {}


def _emits(op: str, *helpers: str, imports: Sequence[str] = ()) -> Callable[[Emitter], Emitter]:
    """Register an emitter, and declare what its output calls.

    *helpers* are the script helpers below that the emitted block calls;
    *imports* are import lines beyond the four every script carries, so a value
    count does not import statsmodels to run ``value_counts``.
    """

    def register(emitter: Emitter) -> Emitter:
        emitter.helpers = helpers  # type: ignore[attr-defined]
        emitter.imports = tuple(imports)  # type: ignore[attr-defined]
        PYTHON_EMITTERS[op] = emitter
        return emitter

    return register


def register(op: str, *helpers: str, imports: Sequence[str] = ()) -> Callable[[Emitter], Emitter]:
    """The public form of :func:`_emits`, for the tier-4-to-6 module next door.

    Tiers 1-3 are emitted from this file. The models that need statsmodels are
    emitted from :mod:`app.services.analysis_codegen_python_models`, which
    registers through here rather than reaching into a private name.
    """
    return _emits(op, *helpers, imports=imports)


def register_helper(name: str, source: str, *, requires: Sequence[str] = ()) -> str:
    """Add a helper that emitters may call, and return its name.

    Registration order is emission order, so a helper registered here may call
    any helper defined above it and none defined below.
    """
    _HELPERS[name] = source
    if requires:
        _HELPER_REQUIRES[name] = tuple(requires)
    return name


def helpers_for(ops: list[str]) -> list[str]:
    """Every helper the emitted blocks call, in definition order, transitively."""
    wanted = {"show"}
    pending = [
        helper
        for op in ops
        for helper in getattr(PYTHON_EMITTERS.get(op), "helpers", ())
        if op in PYTHON_EMITTERS
    ]
    while pending:
        helper = pending.pop()
        if helper in wanted:
            continue
        wanted.add(helper)
        pending.extend(_HELPER_REQUIRES.get(helper, ()))
    return [name for name in _HELPERS if name in wanted]


def imports_for(ops: list[str]) -> list[str]:
    """Import lines the emitted blocks need beyond the standard four, deduplicated."""
    wanted: list[str] = []
    for op in ops:
        for line in getattr(PYTHON_EMITTERS.get(op), "imports", ()):
            if line not in wanted:
                wanted.append(line)
    return sorted(wanted)


# ---------------------------------------------------------------------------
# Header, imports, filter
# ---------------------------------------------------------------------------


def preamble(*, source: str, ops: list[str]) -> Lines:
    """Imports, the load line, and whichever helpers the operations call."""
    lines = [
        "import math",
        "",
        "import numpy as np",
        "import pandas as pd",
        "from scipy import stats",
        *imports_for(ops),
        "",
        "",
    ]
    for helper in helpers_for(ops):
        lines += _helper_source(helper).split("\n") + ["", ""]
    lines += [
        "# Load the data. Edit this line to point at your own file.",
        python_load_statement(source),
    ]
    return lines


def filter_block(spec_filter: dict[str, Any] | None) -> Lines:
    """The spec's row filter, reproducing ``analysis_executor.apply_filter`` exactly."""
    if not spec_filter:
        return [
            "",
            "# No filter was applied; every operation ran over the whole file.",
            f"{DATA} = {FRAME}",
        ]

    column = py_literal(spec_filter["column"])
    operator = spec_filter["operator"]
    value = spec_filter.get("value")
    series = f"{FRAME}[{column}]"
    lines = ["", f"# Filter: {comment_text(spec_filter['column'])} {operator} {value!r}"]

    if operator == "is_null":
        lines.append(f"mask = {series}.isna()")
    elif operator == "is_not_null":
        lines.append(f"mask = {series}.notna()")
    elif operator in ("contains", "not_contains"):
        lines.append("# The value is used as a regular expression, exactly as the product does.")
        match = f"{series}.astype(str).str.contains({py_literal(str(value))}, case=False, na=False)"
        lines.append(f"mask = {'~' if operator == 'not_contains' else ''}{match}")
    elif operator in (">", ">=", "<", "<="):
        lines += [
            f"threshold = pd.to_numeric(pd.Series([{py_literal(value)}]), errors='coerce').iloc[0]",
            f"mask = pd.to_numeric({series}, errors='coerce') {operator} threshold",
        ]
    else:  # "==" or "!="
        lines.append(f"mask = {series} {operator} {py_literal(value)}")

    lines.append(f"{DATA} = {FRAME}[mask.fillna(False)]")
    lines.append(f"print('Filtered to {{}} of {{}} rows.'.format(len({DATA}), len({FRAME})))")
    return lines


# ---------------------------------------------------------------------------
# Tier 1 — descriptive and aggregation
# ---------------------------------------------------------------------------


@_emits("describe")
def _emit_describe(params: dict[str, Any], label: str, index: int) -> Lines:
    columns = params.get("columns")
    chosen = (
        py_literal(list(columns))
        if columns
        else f"[c for c in {DATA}.columns if pd.api.types.is_numeric_dtype({DATA}[c])]"
    )
    return [
        f"columns_{index} = {chosen}",
        f"result_{index} = (",
        f"    {DATA}[columns_{index}].describe().reset_index()",
        "    .rename(columns={'index': 'statistic'})",
        ")",
        f"show({py_literal(label)}, result_{index})",
    ]


_AGG_RENAMES = ("count", "nunique")


@_emits("groupby_aggregate")
def _emit_groupby_aggregate(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by = py_literal(list(params["group_by"]))
    column, agg = params["column"], params["agg"]
    renamed = py_literal(f"{column}_{agg}")
    lines = [f"subset_{index} = {DATA}.dropna(subset={group_by})"]
    if agg not in _AGG_RENAMES:
        lines.append(
            "# count and nunique are meaningful over nulls; the numeric aggregations are not."
        )
        lines.append(f"subset_{index} = subset_{index}.dropna(subset=[{py_literal(column)}])")
    lines += [
        f"result_{index} = (",
        f"    subset_{index}.groupby({group_by}, dropna=True)[{py_literal(column)}]",
        f"    .agg({py_literal(agg)})",
        "    .reset_index()",
        f"    .rename(columns={{{py_literal(column)}: {renamed}}})",
        f"    .sort_values({renamed}, ascending=False)",
        ")",
        f"show({py_literal(label)}, result_{index})",
    ]
    return lines


@_emits("value_counts")
def _emit_value_counts(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    top_n = py_literal(params.get("top_n", DEFAULT_VALUE_COUNTS))
    normalize = bool(params.get("normalize", False))
    return [
        f"counts_{index} = (",
        f"    {DATA}[{column}]",
        f"    .value_counts(normalize={py_literal(normalize)}, dropna=True)",
        f"    .head({top_n})",
        ")",
        f"result_{index} = counts_{index}.reset_index()",
        f"result_{index}.columns = [{column}, {py_literal('proportion' if normalize else 'count')}]",
        f"show({py_literal(label)}, result_{index})",
    ]


@_emits("crosstab")
def _emit_crosstab(params: dict[str, Any], label: str, index: int) -> Lines:
    row, column = _q(params, "row"), _q(params, "column")
    normalize = ", normalize='index'" if params.get("normalize", False) else ""
    return [
        f"table_{index} = pd.crosstab({DATA}[{row}], {DATA}[{column}]{normalize})",
        "# Chi-square needs raw counts, so it is computed on the unnormalized table.",
        f"counts_{index} = pd.crosstab({DATA}[{row}], {DATA}[{column}])",
        f"stats_{index} = {{}}",
        f"if counts_{index}.shape[0] > 1 and counts_{index}.shape[1] > 1 "
        f"and counts_{index}.to_numpy().sum() > 0:",
        f"    chi2, p_value, dof, _ = stats.chi2_contingency(counts_{index})",
        f"    stats_{index} = {{",
        "        'test': 'chi-square test of independence',",
        "        'chi2': round(float(chi2), 4),",
        "        'p_value': round(float(p_value), 6),",
        "        'dof': int(dof),",
        "    }",
        f"result_{index} = table_{index}.reset_index()",
        f"result_{index}.columns = [str(c) for c in result_{index}.columns]",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("histogram")
def _emit_histogram(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    bins = py_literal(params.get("bins", DEFAULT_BINS))
    return [
        f"series_{index} = {DATA}[{column}].dropna()",
        f"counts_{index}, edges_{index} = np.histogram(series_{index}, bins={bins})",
        f"result_{index} = pd.DataFrame({{",
        "    'bin': [",
        f"        {py_literal('{:.4g} – {:.4g}')}.format(edges_{index}[k], edges_{index}[k + 1])",
        f"        for k in range(len(counts_{index}))",
        "    ],",
        f"    'count': counts_{index},",
        "})",
        f"show({py_literal(label)}, result_{index})",
    ]


@_emits("top_n")
def _emit_top_n(params: dict[str, Any], label: str, index: int) -> Lines:
    column, by = _q(params, "column"), _q(params, "by")
    n = py_literal(params.get("n", DEFAULT_TOP_N))
    ascending = py_literal(bool(params.get("ascending", False)))
    return [
        f"subset_{index} = {DATA}[[{column}, {by}]].dropna(subset=[{by}])",
        f"result_{index} = subset_{index}.sort_values({by}, ascending={ascending}).head({n})",
        f"show({py_literal(label)}, result_{index})",
    ]


@_emits("pivot")
def _emit_pivot(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        f"table_{index} = pd.pivot_table(",
        f"    {DATA},",
        f"    index={py_literal(list(params['index']))},",
        f"    columns={_q(params, 'columns')},",
        f"    values={_q(params, 'values')},",
        f"    aggfunc={_q(params, 'agg')},",
        ")",
        f"result_{index} = table_{index}.reset_index()",
        f"result_{index}.columns = [str(c) for c in result_{index}.columns]",
        f"show({py_literal(label)}, result_{index})",
    ]


@_emits("resample")
def _emit_resample(params: dict[str, Any], label: str, index: int) -> Lines:
    date_column, column = _q(params, "date_column"), _q(params, "column")
    agg = params["agg"]
    renamed = py_literal(f"{params['column']}_{agg}")
    return [
        f"subset_{index} = {DATA}[[{date_column}, {column}]].dropna()",
        "# read_csv returns dates as text; the product's frame is already typed, so",
        "# this conversion is a no-op there and changes no value here.",
        f"subset_{index} = subset_{index}.assign(",
        f"    **{{{date_column}: pd.to_datetime(subset_{index}[{date_column}])}}",
        ")",
        f"series_{index} = (",
        f"    subset_{index}.set_index({date_column})[{column}]",
        f"    .resample({_q(params, 'freq')})",
        f"    .agg({py_literal(agg)})",
        ")",
        f"result_{index} = series_{index}.reset_index()",
        f"result_{index}.columns = [{date_column}, {renamed}]",
        f"show({py_literal(label)}, result_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 2 — bivariate
# ---------------------------------------------------------------------------

_CORRELATION_CALLS = {
    "pearson": "stats.pearsonr",
    "spearman": "stats.spearmanr",
    "kendall": "stats.kendalltau",
}


@_emits("correlation_matrix")
def _emit_correlation_matrix(params: dict[str, Any], label: str, index: int) -> Lines:
    columns = py_literal(list(params["columns"]))
    method = params.get("method", "pearson")
    call = _CORRELATION_CALLS[method]
    return [
        f"columns_{index} = {columns}",
        f"subset_{index} = {DATA}[columns_{index}].dropna()",
        f"matrix_{index} = subset_{index}.corr(method={py_literal(method)}).round(4)",
        f"result_{index} = matrix_{index}.reset_index().rename(columns={{'index': 'column'}})",
        f"result_{index}.columns = [str(c) for c in result_{index}.columns]",
        "# Pairwise p-values separate 'these move together' from 'this correlation is",
        "# indistinguishable from zero at this sample size'.",
        f"pairs_{index} = []",
        f"for a_i in range(len(columns_{index})):",
        f"    for b_i in range(a_i + 1, len(columns_{index})):",
        f"        x_name, y_name = columns_{index}[a_i], columns_{index}[b_i]",
        f"        r, p_value = {call}(subset_{index}[x_name], subset_{index}[y_name])",
        f"        pairs_{index}.append({{",
        "            'x': x_name,",
        "            'y': y_name,",
        "            'r': round(float(r), 4),",
        "            'p_value': round(float(p_value), 6),",
        "        })",
        f"stats_{index} = {{'method': {py_literal(method)}, 'pairs': pairs_{index}}}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("scatter_with_fit")
def _emit_scatter_with_fit(params: dict[str, Any], label: str, index: int) -> Lines:
    x, y = _q(params, "x"), _q(params, "y")
    size = _q(params, "size") if params.get("size") is not None else None
    group = _q(params, "color_by") if params.get("color_by") is not None else None
    # Column order matches the product's result table: x, y, size, color.
    columns = ", ".join(name for name in (x, y, size, group) if name)
    required = ", ".join(name for name in (x, y, size) if name)
    subset = [f"subset_{index} = {DATA}[[{columns}]].dropna(subset=[{required}])"]
    if group:
        missing = py_literal(MISSING_GROUP_LABEL)
        subset += [
            "# A missing color label is kept and named: the point is still a measurement.",
            f"subset_{index}[{group}] = (",
            f"    subset_{index}[{group}].astype('string').fillna({missing}).astype(object)",
            ")",
        ]
    return subset + [
        f"fit_{index} = stats.linregress(subset_{index}[{x}], subset_{index}[{y}])",
        f"result_{index} = subset_{index}",
        f"stats_{index} = {{",
        f"    'slope': round(float(fit_{index}.slope), 6),",
        f"    'intercept': round(float(fit_{index}.intercept), 6),",
        f"    'r': round(float(fit_{index}.rvalue), 4),",
        f"    'r_squared': round(float(fit_{index}.rvalue ** 2), 4),",
        f"    'p_value': round(float(fit_{index}.pvalue), 6),",
        f"    'std_err': round(float(fit_{index}.stderr), 6),",
        "}",
        f"show({py_literal(label)}, result_{index}.head(), stats_{index})",
    ]


@_emits("group_comparison")
def _emit_group_comparison(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"subset_{index} = {DATA}[[{group_by}, {column}]].dropna()",
        f"grouped_{index} = subset_{index}.groupby({group_by})[{column}]",
        f"result_{index} = grouped_{index}.agg(['count', 'mean', 'std', 'median']).reset_index()",
        "# A 95% interval on each group mean: bare means do not show whether the",
        "# groups are distinguishable, which is the point of a comparison.",
        f"ci_low_{index}, ci_high_{index} = [], []",
        f"for _, row in result_{index}.iterrows():",
        "    n, mean, sd = row['count'], row['mean'], row['std']",
        "    if n > 1 and pd.notna(sd) and sd > 0:",
        f"        margin = stats.t.ppf({(1 + CONFIDENCE_LEVEL) / 2!r}, n - 1) * (sd / math.sqrt(n))",
        f"        ci_low_{index}.append(round(float(mean - margin), 4))",
        f"        ci_high_{index}.append(round(float(mean + margin), 4))",
        "    else:",
        f"        ci_low_{index}.append(None)",
        f"        ci_high_{index}.append(None)",
        f"result_{index}['ci95_low'] = ci_low_{index}",
        f"result_{index}['ci95_high'] = ci_high_{index}",
        "",
        f"groups_{index} = [g.to_numpy() for _, g in grouped_{index} if len(g) > 1]",
        f"stats_{index} = {{}}",
        f"if groups_{index} and all(float(np.std(g)) == 0.0 for g in groups_{index}):",
        f"    stats_{index} = {{",
        "        'test': 'not computed',",
        "        'reason': 'every group has zero variance, so no significance test applies',",
        "    }",
        f"elif len(groups_{index}) == 2:",
        f"    statistic, p_value = stats.ttest_ind("
        f"groups_{index}[0], groups_{index}[1], equal_var=False)",
        f"    stats_{index} = {{",
        "        'test': \"Welch's t-test (two groups, unequal variance)\",",
        "        'statistic': round(float(statistic), 4),",
        "        'p_value': round(float(p_value), 6),",
        "    }",
        f"elif len(groups_{index}) > 2:",
        f"    statistic, p_value = stats.f_oneway(*groups_{index})",
        f"    stats_{index} = {{",
        "        'test': 'one-way ANOVA',",
        "        'statistic': round(float(statistic), 4),",
        "        'p_value': round(float(p_value), 6),",
        "    }",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 3 — inferential
# ---------------------------------------------------------------------------

_ALTERNATIVES = ("two-sided", "less", "greater")


def _alternative(params: dict[str, Any]) -> str:
    alternative = params.get("alternative", "two-sided")
    return py_literal(alternative if alternative in _ALTERNATIVES else "two-sided")


def _emit_ttest_one_sample(params: dict[str, Any], label: str, index: int) -> Lines:
    column, mu = _q(params, "column"), py_literal(float(params["mu"]))
    return [
        f"values_{index} = pd.to_numeric({DATA}[{column}], errors='coerce')"
        ".dropna().to_numpy(dtype=float)",
        f"test_{index} = stats.ttest_1samp("
        f"values_{index}, {mu}, alternative={_alternative(params)})",
        f"low_{index}, high_{index} = mean_ci(values_{index})",
        f"sd_{index} = float(values_{index}.std(ddof=1))",
        f"result_{index} = pd.DataFrame([{{",
        f"    'measure': {column},",
        f"    'n': int(values_{index}.size),",
        f"    'mean': float(values_{index}.mean()),",
        f"    'sd': sd_{index},",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        f"    'tested_against': {mu},",
        "}])",
        f"stats_{index} = {{",
        f"    'test': 'One-sample t-test against {{:g}}'.format({mu}),",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'dof': int(values_{index}.size - 1),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'mean_difference': float(values_{index}.mean() - {mu}),",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        f"    'effect_size': float((values_{index}.mean() - {mu}) / sd_{index})"
        f" if sd_{index} > 0 else float('nan'),",
        f"    'normality_p': normality_p(values_{index}),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_ttest_independent(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    equal_var = py_literal(bool(params.get("equal_var", False)))
    return [
        f"labels_{index}, groups_{index} = split_groups({DATA}, {group_by}, {column})",
        f"first_{index}, second_{index} = groups_{index}",
        f"test_{index} = stats.ttest_ind(",
        f"    first_{index}, second_{index},"
        f" equal_var={equal_var}, alternative={_alternative(params)}",
        ")",
        f"low_{index}, high_{index} = mean_difference_ci("
        f"first_{index}, second_{index}, equal_var={equal_var})",
        f"d_{index}, g_{index} = cohens_d(first_{index}, second_{index})",
        f"result_{index} = group_summary(labels_{index}, groups_{index}, {group_by})",
        f"stats_{index} = {{",
        f"    'comparison': '{{}} minus {{}}'.format(*labels_{index}),",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'dof': float(test_{index}.df),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'mean_difference': float(first_{index}.mean() - second_{index}.mean()),",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        f"    'effect_size': d_{index},",
        f"    'hedges_g': g_{index},",
        f"    'levene_p': float(stats.levene(*groups_{index}, center='median').pvalue),",
        f"    'normality_p': [normality_p(g) for g in groups_{index}],",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_ttest_paired(params: dict[str, Any], label: str, index: int) -> Lines:
    column, column2 = _q(params, "column"), _q(params, "column2")
    return [
        f"pair_{index} = pd.DataFrame({{",
        f"    {column}: pd.to_numeric({DATA}[{column}], errors='coerce'),",
        f"    {column2}: pd.to_numeric({DATA}[{column2}], errors='coerce'),",
        "}).dropna()",
        f"first_{index} = pair_{index}[{column}].to_numpy(dtype=float)",
        f"second_{index} = pair_{index}[{column2}].to_numpy(dtype=float)",
        f"differences_{index} = first_{index} - second_{index}",
        f"test_{index} = stats.ttest_rel("
        f"first_{index}, second_{index}, alternative={_alternative(params)})",
        f"low_{index}, high_{index} = mean_ci(differences_{index})",
        f"sd_{index} = float(differences_{index}.std(ddof=1))",
        f"result_{index} = pd.DataFrame([",
        f"    {{'measure': {column}, 'n': len(pair_{index}),"
        f" 'mean': float(first_{index}.mean())}},",
        f"    {{'measure': {column2}, 'n': len(pair_{index}),"
        f" 'mean': float(second_{index}.mean())}},",
        f"    {{'measure': 'difference', 'n': len(pair_{index}),"
        f" 'mean': float(differences_{index}.mean())}},",
        "])",
        f"stats_{index} = {{",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'dof': int(len(pair_{index}) - 1),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'mean_difference': float(differences_{index}.mean()),",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        f"    'effect_size': float(differences_{index}.mean() / sd_{index})"
        f" if sd_{index} > 0 else float('nan'),",
        f"    'normality_p': normality_p(differences_{index}),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


_TTEST_KINDS = {
    "one_sample": _emit_ttest_one_sample,
    "independent": _emit_ttest_independent,
    "paired": _emit_ttest_paired,
}


@_emits(
    "ttest",
    "split_groups",
    "mean_ci",
    "mean_difference_ci",
    "cohens_d",
    "group_summary",
    "normality_p",
)
def _emit_ttest(params: dict[str, Any], label: str, index: int) -> Lines:
    kind = str(params.get("kind"))
    emitter = _TTEST_KINDS.get(kind)
    if emitter is None:  # pragma: no cover - validation rejects this first
        return [f"# ttest: unknown kind {kind!r}; no code emitted."]
    return [f"# {kind.replace('_', '-')} t-test"] + emitter(params, label, index)


@_emits("anova", "split_groups", "mean_ci", "group_summary", "normality_p")
def _emit_anova(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"labels_{index}, groups_{index} = split_groups({DATA}, {group_by}, {column})",
        f"test_{index} = stats.f_oneway(*groups_{index})",
        f"combined_{index} = np.concatenate(groups_{index})",
        f"grand_mean_{index} = float(combined_{index}.mean())",
        f"ss_total_{index} = float(((combined_{index} - grand_mean_{index}) ** 2).sum())",
        f"ss_between_{index} = float(",
        f"    sum(g.size * (g.mean() - grand_mean_{index}) ** 2 for g in groups_{index})",
        ")",
        f"ss_within_{index} = ss_total_{index} - ss_between_{index}",
        f"df_between_{index} = len(groups_{index}) - 1",
        f"df_within_{index} = int(combined_{index}.size) - len(groups_{index})",
        f"ms_within_{index} = ss_within_{index} / df_within_{index}",
        f"result_{index} = group_summary(labels_{index}, groups_{index}, {group_by})",
        f"stats_{index} = {{",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'df_between': int(df_between_{index}),",
        f"    'df_within': int(df_within_{index}),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'effect_size': ss_between_{index} / ss_total_{index},",
        "    'omega_squared': (",
        f"        (ss_between_{index} - df_between_{index} * ms_within_{index})",
        f"        / (ss_total_{index} + ms_within_{index})",
        "    ),",
        f"    'levene_p': float(stats.levene(*groups_{index}, center='median').pvalue),",
        f"    'normality_p': [normality_p(g) for g in groups_{index}],",
        "}",
        "# Running every pairwise t-test after a significant F is the classic way to",
        "# manufacture a false positive; Tukey's HSD adjusts for how many are made.",
        f"tukey_{index} = stats.tukey_hsd(*groups_{index})",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
        f"print(tukey_{index})",
    ]


@_emits("kruskal", "split_groups", "rank_summary")
def _emit_kruskal(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"labels_{index}, groups_{index} = split_groups({DATA}, {group_by}, {column})",
        f"test_{index} = stats.kruskal(*groups_{index})",
        f"n_{index} = int(sum(g.size for g in groups_{index}))",
        f"k_{index} = len(groups_{index})",
        f"result_{index} = rank_summary(labels_{index}, groups_{index}, {group_by})",
        f"stats_{index} = {{",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'dof': int(k_{index} - 1),",
        f"    'p_value': float(test_{index}.pvalue),",
        "    # Epsilon squared: the rank analogue of eta squared.",
        f"    'effect_size': (float(test_{index}.statistic) - k_{index} + 1)"
        f" / (n_{index} - k_{index}),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("mannwhitney", "split_groups", "rank_summary")
def _emit_mannwhitney(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"labels_{index}, groups_{index} = split_groups({DATA}, {group_by}, {column})",
        f"first_{index}, second_{index} = groups_{index}",
        f"test_{index} = stats.mannwhitneyu(",
        f"    first_{index}, second_{index}, alternative={_alternative(params)}",
        ")",
        f"result_{index} = rank_summary(labels_{index}, groups_{index}, {group_by})",
        "# Hodges-Lehmann is a median over all pairs, so it is skipped rather than",
        "# allocating a matrix that dwarfs the dataset.",
        f"pairs_{index} = first_{index}.size * second_{index}.size",
        f"shift_{index} = (",
        f"    float(np.median(first_{index}[:, None] - second_{index}[None, :]))",
        f"    if pairs_{index} <= {MAX_HODGES_LEHMANN_PAIRS} else float('nan')",
        ")",
        f"stats_{index} = {{",
        f"    'comparison': '{{}} minus {{}}'.format(*labels_{index}),",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'median_difference': float(np.median(first_{index}) - np.median(second_{index})),",
        f"    'hodges_lehmann_shift': shift_{index},",
        "    # Rank-biserial correlation, signed so a negative value means the first",
        "    # group ranks below the second.",
        f"    'effect_size': 2 * float(test_{index}.statistic) / pairs_{index} - 1,",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("wilcoxon")
def _emit_wilcoxon(params: dict[str, Any], label: str, index: int) -> Lines:
    column, column2 = _q(params, "column"), _q(params, "column2")
    return [
        f"pair_{index} = pd.DataFrame({{",
        f"    {column}: pd.to_numeric({DATA}[{column}], errors='coerce'),",
        f"    {column2}: pd.to_numeric({DATA}[{column2}], errors='coerce'),",
        "}).dropna()",
        f"first_{index} = pair_{index}[{column}].to_numpy(dtype=float)",
        f"second_{index} = pair_{index}[{column2}].to_numpy(dtype=float)",
        f"differences_{index} = first_{index} - second_{index}",
        f"test_{index} = stats.wilcoxon("
        f"first_{index}, second_{index}, alternative={_alternative(params)})",
        "# Matched-pairs rank-biserial: the rank-weighted balance of signs.",
        f"nonzero_{index} = differences_{index}[differences_{index} != 0]",
        f"ranks_{index} = stats.rankdata(np.abs(nonzero_{index}))",
        f"result_{index} = pd.DataFrame([",
        f"    {{'measure': {column}, 'n': len(pair_{index}),"
        f" 'median': float(np.median(first_{index}))}},",
        f"    {{'measure': {column2}, 'n': len(pair_{index}),"
        f" 'median': float(np.median(second_{index}))}},",
        f"    {{'measure': 'difference', 'n': len(pair_{index}),"
        f" 'median': float(np.median(differences_{index}))}},",
        "])",
        f"stats_{index} = {{",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'n_pairs': int(len(pair_{index})),",
        f"    'median_difference': float(np.median(differences_{index})),",
        "    'effect_size': float(",
        f"        (ranks_{index}[nonzero_{index} > 0].sum()"
        f" - ranks_{index}[nonzero_{index} < 0].sum())",
        f"        / ranks_{index}.sum()",
        "    ),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_chi_square_independence(params: dict[str, Any], label: str, index: int) -> Lines:
    row, column = _q(params, "row"), _q(params, "column")
    return [
        f"frame_{index} = {DATA}[[{row}, {column}]].dropna()",
        f"observed_{index} = pd.crosstab(frame_{index}[{row}], frame_{index}[{column}])",
        "# An all-zero row or column carries no information and makes the test",
        "# undefined, so it is dropped rather than left to raise.",
        f"observed_{index} = observed_{index}.loc[",
        f"    observed_{index}.sum(axis=1) > 0, observed_{index}.sum(axis=0) > 0",
        "]",
        f"corrected_{index} = stats.chi2_contingency(observed_{index})",
        f"uncorrected_{index} = stats.chi2_contingency(observed_{index}, correction=False)",
        f"total_{index} = int(observed_{index}.to_numpy().sum())",
        f"smaller_{index} = min(observed_{index}.shape[0] - 1, observed_{index}.shape[1] - 1)",
        f"result_{index} = observed_{index}.reset_index()",
        f"result_{index}.columns = [str(c) for c in result_{index}.columns]",
        f"stats_{index} = {{",
        f"    'statistic': float(corrected_{index}.statistic),",
        f"    'dof': int(corrected_{index}.dof),",
        f"    'p_value': float(corrected_{index}.pvalue),",
        f"    'continuity_correction': observed_{index}.shape == (2, 2),",
        "    # Cramer's V comes from the uncorrected statistic by convention: the",
        "    # continuity correction exists to fix the p-value, not the effect size.",
        "    'effect_size': math.sqrt(",
        f"        float(uncorrected_{index}.statistic) / (total_{index} * smaller_{index})",
        "    ),",
        f"    'smallest_expected_count': float(corrected_{index}.expected_freq.min()),",
        "}",
        f"if observed_{index}.shape == (2, 2):",
        "    # scipy reports the sample odds ratio (ad/bc); R's fisher.test reports the",
        "    # conditional maximum-likelihood estimate, which is a different number.",
        f"    odds_ratio, fisher_p = stats.fisher_exact(observed_{index}.to_numpy())",
        f"    stats_{index}['fisher_odds_ratio'] = float(odds_ratio)",
        f"    stats_{index}['fisher_p_value'] = float(fisher_p)",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_chi_square_goodness_of_fit(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    return [
        "# Tested against a uniform distribution — equal counts in every category.",
        "# The pipeline does not accept a hypothesized distribution from the model,",
        "# because the model does not supply numbers.",
        f"counts_{index} = {DATA}[{column}].value_counts(dropna=True).sort_index()",
        f"total_{index} = int(counts_{index}.sum())",
        f"expected_{index} = total_{index} / len(counts_{index})",
        f"test_{index} = stats.chisquare(counts_{index}.to_numpy(dtype=float))",
        f"result_{index} = pd.DataFrame({{",
        f"    {column}: [str(value) for value in counts_{index}.index],",
        f"    'observed': counts_{index}.to_numpy(dtype=int),",
        f"    'expected': [expected_{index}] * len(counts_{index}),",
        "})",
        f"stats_{index} = {{",
        f"    'statistic': float(test_{index}.statistic),",
        f"    'dof': int(len(counts_{index}) - 1),",
        f"    'p_value': float(test_{index}.pvalue),",
        f"    'expected_per_category': float(expected_{index}),",
        "    # Cohen's w.",
        f"    'effect_size': math.sqrt(float(test_{index}.statistic) / total_{index}),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("chi_square")
def _emit_chi_square(params: dict[str, Any], label: str, index: int) -> Lines:
    if str(params.get("kind")) == "goodness_of_fit":
        return _emit_chi_square_goodness_of_fit(params, label, index)
    return _emit_chi_square_independence(params, label, index)


_Z_TAIL = {
    "two-sided": "float(2 * stats.norm.sf(abs({z})))",
    "greater": "float(stats.norm.sf({z}))",
    "less": "float(stats.norm.cdf({z}))",
}


def _z_p_value(params: dict[str, Any], variable: str) -> str:
    alternative = params.get("alternative", "two-sided")
    return _Z_TAIL.get(str(alternative), _Z_TAIL["two-sided"]).format(z=variable)


def _emit_proportion_one_sample(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    success = py_literal(str(params["success_value"]))
    p0 = py_literal(float(params["p0"]))
    return [
        f"present_{index} = {DATA}[{column}].dropna()",
        f"successes_{index} = int((present_{index}.astype(str) == {success}).sum())",
        f"n_{index} = int(present_{index}.size)",
        f"proportion_{index} = successes_{index} / n_{index}",
        f"se_{index} = math.sqrt({p0} * (1 - {p0}) / n_{index})",
        f"z_{index} = (proportion_{index} - {p0}) / se_{index} if se_{index} > 0 else float('nan')",
        f"low_{index}, high_{index} = wilson_ci(successes_{index}, n_{index})",
        f"result_{index} = pd.DataFrame([{{",
        f"    {column}: {success},",
        f"    'n': n_{index},",
        f"    'successes': successes_{index},",
        f"    'proportion': proportion_{index},",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        f"    'tested_against': {p0},",
        "}])",
        f"stats_{index} = {{",
        f"    'statistic': z_{index},",
        f"    'p_value': {_z_p_value(params, f'z_{index}')},",
        f"    'proportion': proportion_{index},",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        "    # Cohen's h, on the arcsine scale.",
        f"    'effect_size': 2 * math.asin(math.sqrt(proportion_{index}))"
        f" - 2 * math.asin(math.sqrt({p0})),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_proportion_two_sample(params: dict[str, Any], label: str, index: int) -> Lines:
    column, group_by = _q(params, "column"), _q(params, "group_by")
    success = py_literal(str(params["success_value"]))
    return [
        f"frame_{index} = {DATA}[[{group_by}, {column}]].dropna()",
        f"labels_{index} = sorted(str(value) for value in frame_{index}[{group_by}].unique())",
        f"counts_{index} = []",
        f"for label in labels_{index}:",
        f"    column_{index} = frame_{index}.loc[",
        f"        frame_{index}[{group_by}].astype(str) == label, {column}",
        "    ]",
        f"    counts_{index}.append(",
        f"        (int((column_{index}.astype(str) == {success}).sum()), int(column_{index}.size))",
        "    )",
        f"(successes1_{index}, n1_{index}), (successes2_{index}, n2_{index}) = counts_{index}",
        f"p1_{index}, p2_{index} = successes1_{index} / n1_{index}, "
        f"successes2_{index} / n2_{index}",
        f"pooled_{index} = (successes1_{index} + successes2_{index}) / (n1_{index} + n2_{index})",
        f"se_{index} = math.sqrt(",
        f"    pooled_{index} * (1 - pooled_{index}) * (1 / n1_{index} + 1 / n2_{index})",
        ")",
        f"z_{index} = (p1_{index} - p2_{index}) / se_{index} if se_{index} > 0 else float('nan')",
        f"low_{index}, high_{index} = proportion_difference_ci(",
        f"    successes1_{index}, n1_{index}, successes2_{index}, n2_{index}",
        ")",
        f"rows_{index} = []",
        f"for label, (successes, n) in zip(labels_{index}, counts_{index}):",
        "    ci_low, ci_high = wilson_ci(successes, n)",
        f"    rows_{index}.append({{",
        f"        {group_by}: label,",
        "        'n': n,",
        "        'successes': successes,",
        "        'proportion': successes / n,",
        "        'ci95_low': ci_low,",
        "        'ci95_high': ci_high,",
        "    })",
        f"result_{index} = pd.DataFrame(rows_{index})",
        f"stats_{index} = {{",
        f"    'comparison': '{{}} minus {{}}'.format(*labels_{index}),",
        f"    'statistic': z_{index},",
        f"    'p_value': {_z_p_value(params, f'z_{index}')},",
        f"    'difference': p1_{index} - p2_{index},",
        f"    'ci95_low': low_{index},",
        f"    'ci95_high': high_{index},",
        "    # Cohen's h, on the arcsine scale.",
        f"    'effect_size': 2 * math.asin(math.sqrt(p1_{index}))"
        f" - 2 * math.asin(math.sqrt(p2_{index})),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("proportion_test", "wilson_ci", "proportion_difference_ci")
def _emit_proportion_test(params: dict[str, Any], label: str, index: int) -> Lines:
    if params.get("group_by") is not None:
        return _emit_proportion_two_sample(params, label, index)
    return _emit_proportion_one_sample(params, label, index)


_NORMALITY_ROW = [
    "def normality_row(values, group_label):",
    '    """One row of the normality table: shape, spread, and the test."""',
    "    p_value = normality_p(values)",
    "    return {",
    "        'group': group_label,",
    "        'n': int(values.size),",
    "        'mean': float(values.mean()),",
    "        'sd': float(values.std(ddof=1)) if values.size > 1 else None,",
    "        'skewness': float(stats.skew(values, bias=False)) if values.size > 2 else None,",
    "        'kurtosis': float(stats.kurtosis(values, bias=False)) if values.size > 3 else None,",
    "        'shapiro_p': p_value,",
    f"        'normal_at_0.05': None if math.isnan(p_value) else bool(p_value >= {ALPHA!r}),",
    "    }",
]


@_emits("normality_test", "split_groups", "normality_p")
def _emit_normality_test(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    group_by = params.get("group_by")
    lines = list(_NORMALITY_ROW)
    lines += [
        "",
        "# The product also renders a prose verdict from these numbers; the numbers",
        "# themselves are what is reproduced here.",
        f"series_{index} = pd.to_numeric({DATA}[{column}], errors='coerce')"
        ".dropna().to_numpy(dtype=float)",
    ]
    if group_by is None:
        lines += [
            f"result_{index} = pd.DataFrame([normality_row(series_{index}, '(all rows)')])",
        ]
    else:
        lines += [
            f"labels_{index}, groups_{index} = split_groups("
            f"{DATA}, {py_literal(group_by)}, {column})",
            f"result_{index} = pd.DataFrame([",
            "    normality_row(values, label)",
            f"    for label, values in zip(labels_{index}, groups_{index})",
            "    if values.size >= 3",
            f"]).rename(columns={{'group': {py_literal(group_by)}}})",
        ]
    lines.append(f"show({py_literal(label)}, result_{index})")
    return lines
