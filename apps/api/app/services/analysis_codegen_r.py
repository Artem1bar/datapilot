"""R source for a validated analysis spec — the second half of the trust bridge.

Same job as :mod:`app.services.analysis_codegen_python`, different audience.
Plenty of the people who most need to check a survey estimate work in R, and
handing them Python is handing them a translation exercise rather than a check.

Three rules, one of them specific to this dialect.

**Nothing but a literal.** Every column name and category value crosses into
emitted source through :func:`r_literal`. Names never appear as identifiers:
columns are reached with ``d[["name"]]`` and, inside dplyr verbs, with
``.data[["name"]]`` or ``all_of(c("name"))``. Backtick quoting is deliberately
avoided — a name containing a backtick would need escaping rules that vary by
context, and the string form has none of that.

**Idiomatic where R is idiomatic.** dplyr and tidyr do the Tier 1 aggregation;
base ``stats`` does the tests. Formulas are built over a fixed ``group``/
``value`` frame rather than over user column names, so no formula ever has to
quote an arbitrary identifier.

**Say where R differs rather than approximate.** R's defaults are not scipy's
in several places — exact versus asymptotic rank tests, the odds ratio
``fisher.test`` reports, the continuity correction in ``prop.test``, the absence
of Levene's test from base R. Each is called out in a comment beside the line it
affects, and the number the product reported is computed the product's way, so
the two agree.

Adding an operation means registering one emitter::

    from app.services.analysis_codegen_r import R_EMITTERS, r_literal

    def _emit_ols(params, label, index):
        return [f"result_{index} <- lm({r_literal(params['formula'])}, data = d)"]

    R_EMITTERS["ols"] = _emit_ols
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable, Sequence
from typing import Any

Lines = list[str]
Emitter = Callable[[dict[str, Any], str, int], Lines]

FRAME = "df_raw"
DATA = "d"

# Mirrors analysis_executor's defaults; a test asserts they have not drifted.
DEFAULT_TOP_N = 10
DEFAULT_VALUE_COUNTS = 20
DEFAULT_BINS = 10

CONFIDENCE_LEVEL = 0.95
ALPHA = 0.05

# R's own escapes for the characters that would otherwise end a string literal
# or a line. Everything else printable passes through as UTF-8.
_R_STRING_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def r_literal(value: Any) -> str:
    """Render *value* as R source.

    The only sanctioned way for data to enter emitted code. Control characters
    beyond the named escapes use the braced ``\\u{...}`` form, which — unlike
    ``\\x41`` — cannot swallow a following hex digit.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, numbers.Integral):
        return repr(int(value))
    if isinstance(value, numbers.Real):
        as_float = float(value)
        if math.isnan(as_float):
            return "NaN"
        if math.isinf(as_float):
            return "Inf" if as_float > 0 else "-Inf"
        return repr(as_float)
    if isinstance(value, (list, tuple)):
        return "c(" + ", ".join(r_literal(item) for item in value) + ")"

    text = value if isinstance(value, str) else str(value)
    body = "".join(
        _R_STRING_ESCAPES.get(char)
        or (f"\\u{{{ord(char):x}}}" if ord(char) < 0x20 or ord(char) == 0x7F else char)
        for char in text
    )
    return f'"{body}"'


def r_comment_text(text: Any) -> str:
    """Fold a user-supplied string onto one line, so it cannot escape a comment."""
    return " ".join(str(text).split())


def r_load_statement(source: str) -> str:
    """The single statement that loads the data.

    ``check.names = FALSE`` is not optional: R would otherwise rewrite every
    column name that is not a syntactic identifier, and the export would then be
    reading columns the product never touched.
    """
    return (
        f"{FRAME} <- read.csv({r_literal(source)}, check.names = FALSE, stringsAsFactors = FALSE)"
    )


def _q(params: dict[str, Any], key: str) -> str:
    return r_literal(params[key])


# ---------------------------------------------------------------------------
# Helpers emitted into the script
# ---------------------------------------------------------------------------

_HELPERS: dict[str, str] = {
    "show_result": """show_result <- function(title, frame = NULL, values = NULL) {
  cat("\\n=== ", title, " ===\\n", sep = "")
  if (!is.null(frame)) print(as.data.frame(frame), row.names = FALSE)
  for (key in names(values)) {
    cat("  ", key, ": ", paste(format(values[[key]]), collapse = ", "), "\\n", sep = "")
  }
}""",
    "num": """# read.csv gives text for anything with a stray non-numeric cell; coerce the
# same way the product does, turning what cannot be read into NA.
num <- function(x) suppressWarnings(as.numeric(as.character(x)))""",
    "split_groups": """split_groups <- function(frame, group_column, value_column) {
  # Groups in sorted label order, dropping rows missing either column. Sorted
  # order is what makes the sign of a difference stable: it is "alphabetically
  # first minus second", not "whichever row came first in the upload".
  pair <- data.frame(
    group = as.character(frame[[group_column]]),
    value = num(frame[[value_column]]),
    stringsAsFactors = FALSE
  )
  pair <- pair[!is.na(pair$group) & !is.na(pair$value), , drop = FALSE]
  pair$group <- factor(pair$group, levels = sort(unique(pair$group)))
  pair
}""",
    "mean_ci": """mean_ci <- function(values, level = __LEVEL__) {
  # Two-sided t interval, computed here rather than read off t.test() so that a
  # one-sided test still reports the two-sided interval the product reports.
  n <- length(values)
  if (n < 2) return(c(NA_real_, NA_real_))
  spread <- sd(values)
  centre <- mean(values)
  if (spread <= 0) return(c(centre, centre))
  margin <- qt(1 - (1 - level) / 2, n - 1) * spread / sqrt(n)
  c(centre - margin, centre + margin)
}""",
    "mean_difference_ci": """mean_difference_ci <- function(a, b, equal_var = FALSE, level = __LEVEL__) {
  n1 <- length(a); n2 <- length(b)
  var1 <- var(a); var2 <- var(b)
  if (equal_var) {
    pooled <- ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    standard_error <- sqrt(pooled * (1 / n1 + 1 / n2))
    dof <- n1 + n2 - 2
  } else {
    standard_error <- sqrt(var1 / n1 + var2 / n2)
    dof <- (var1 / n1 + var2 / n2)^2 /
      ((var1 / n1)^2 / (n1 - 1) + (var2 / n2)^2 / (n2 - 1))
  }
  difference <- mean(a) - mean(b)
  margin <- qt(1 - (1 - level) / 2, dof) * standard_error
  c(difference - margin, difference + margin)
}""",
    "cohens_d": """cohens_d <- function(a, b) {
  # Returns c(d, Hedges' g); g carries the small-sample correction d lacks.
  n1 <- length(a); n2 <- length(b)
  pooled <- ((n1 - 1) * var(a) + (n2 - 1) * var(b)) / (n1 + n2 - 2)
  if (pooled <= 0) return(c(NA_real_, NA_real_))
  d <- (mean(a) - mean(b)) / sqrt(pooled)
  c(d, d * (1 - 3 / (4 * (n1 + n2) - 9)))
}""",
    "group_summary": """group_summary <- function(pair, group_column) {
  rows <- lapply(levels(pair$group), function(label) {
    values <- pair$value[pair$group == label]
    bounds <- mean_ci(values)
    data.frame(
      label = label,
      n = length(values),
      mean = mean(values),
      sd = if (length(values) > 1) sd(values) else NA_real_,
      median = median(values),
      ci95_low = bounds[1],
      ci95_high = bounds[2],
      stringsAsFactors = FALSE
    )
  })
  out <- do.call(rbind, rows)
  names(out)[1] <- group_column
  out
}""",
    "rank_summary": """rank_summary <- function(pair, group_column) {
  pair$rank <- rank(pair$value)  # average ranks for ties, as scipy's rankdata does
  rows <- lapply(levels(pair$group), function(label) {
    block <- pair[pair$group == label, , drop = FALSE]
    data.frame(
      label = label,
      n = nrow(block),
      median = median(block$value),
      q1 = quantile(block$value, 0.25, names = FALSE),
      q3 = quantile(block$value, 0.75, names = FALSE),
      mean_rank = mean(block$rank),
      stringsAsFactors = FALSE
    )
  })
  out <- do.call(rbind, rows)
  names(out)[1] <- group_column
  out
}""",
    "shape_stats": """# Base R has no skewness or kurtosis. These are the bias-corrected G1 and
# excess-G2 estimators, which is what the product reports.
skewness <- function(v) {
  n <- length(v)
  (n / ((n - 1) * (n - 2))) * sum(((v - mean(v)) / sd(v))^3)
}
kurtosis <- function(v) {
  n <- length(v)
  ((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * sum(((v - mean(v)) / sd(v))^4) -
    (3 * (n - 1)^2) / ((n - 2) * (n - 3))
}""",
    "normality_p": """normality_p <- function(values) {
  # shapiro.test is defined for 3 <= n <= 5000. Past that the product switches
  # to D'Agostino K-squared, which base R does not have: use
  # moments::agostino.test() there rather than reading an out-of-range p-value.
  values <- values[is.finite(values)]
  if (length(values) < 3 || sd(values) == 0) return(NA_real_)
  if (length(values) > 5000) return(NA_real_)
  shapiro.test(values)$p.value
}""",
    "wilson_ci": """wilson_ci <- function(successes, n, level = __LEVEL__) {
  # Wilson score interval: the normal approximation runs past 0 and 1 and
  # collapses to zero width at p = 0, exactly where honesty matters most.
  z <- qnorm(1 - (1 - level) / 2)
  p <- successes / n
  denominator <- 1 + z^2 / n
  centre <- (p + z^2 / (2 * n)) / denominator
  margin <- (z / denominator) * sqrt(p * (1 - p) / n + z^2 / (4 * n^2))
  c(max(0, centre - margin), min(1, centre + margin))
}""",
    "proportion_difference_ci": """proportion_difference_ci <- function(successes1, n1, successes2, n2) {
  # Newcombe's interval, built from the two Wilson intervals.
  first <- wilson_ci(successes1, n1)
  second <- wilson_ci(successes2, n2)
  p1 <- successes1 / n1
  p2 <- successes2 / n2
  difference <- p1 - p2
  lower <- difference - sqrt((p1 - first[1])^2 + (second[2] - p2)^2)
  upper <- difference + sqrt((first[2] - p1)^2 + (p2 - second[1])^2)
  c(max(-1, lower), min(1, upper))
}""",
}

_HELPER_REQUIRES: dict[str, tuple[str, ...]] = {
    "split_groups": ("num",),
    "group_summary": ("mean_ci",),
    "rank_summary": ("num",),
    "proportion_difference_ci": ("wilson_ci",),
}


# Substituted rather than %-formatted: emitted R is full of % operators.
_LEVEL_TOKEN = "__LEVEL__"


def _helper_source(name: str) -> str:
    return _HELPERS[name].replace(_LEVEL_TOKEN, r_literal(CONFIDENCE_LEVEL))


R_EMITTERS: dict[str, Emitter] = {}


def _emits(op: str, *helpers: str, packages: Sequence[str] = ()) -> Callable[[Emitter], Emitter]:
    """Register an emitter, and declare what its output needs.

    *helpers* are the script helpers below that the emitted block calls;
    *packages* are CRAN packages beyond dplyr and tidyr that it attaches, so a
    script that runs no survey estimate does not require the survey package.
    """

    def register(emitter: Emitter) -> Emitter:
        emitter.helpers = helpers  # type: ignore[attr-defined]
        emitter.packages = tuple(packages)  # type: ignore[attr-defined]
        R_EMITTERS[op] = emitter
        return emitter

    return register


def register(op: str, *helpers: str, packages: Sequence[str] = ()) -> Callable[[Emitter], Emitter]:
    """The public form of :func:`_emits`, for the tier-4-to-6 module next door."""
    return _emits(op, *helpers, packages=packages)


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
    wanted = {"show_result", "num"}
    pending = [helper for op in ops for helper in getattr(R_EMITTERS.get(op), "helpers", ()) if op]
    while pending:
        helper = pending.pop()
        if helper in wanted:
            continue
        wanted.add(helper)
        pending.extend(_HELPER_REQUIRES.get(helper, ()))
    return [name for name in _HELPERS if name in wanted]


# Packages that are required but never attached, because attaching them would
# shadow a function the emitted script already calls. MASS::select masks
# dplyr::select, which Tier 1's top_n uses, so a script that ran both would
# break on a name collision rather than on anything statistical. They are named
# in the install line and called through their namespace instead.
_NEVER_ATTACH = frozenset({"MASS"})


def packages_for(ops: list[str]) -> list[str]:
    """CRAN packages the emitted blocks need beyond dplyr and tidyr."""
    wanted: list[str] = []
    for op in ops:
        for name in getattr(R_EMITTERS.get(op), "packages", ()):
            if name not in wanted:
                wanted.append(name)
    return sorted(wanted)


def preamble(*, source: str, ops: list[str]) -> Lines:
    """Libraries, collation, the load line, and whichever helpers are called."""
    extra = packages_for(ops)
    lines = [
        "suppressPackageStartupMessages({",
        "  library(dplyr)",
        "  library(tidyr)",
        *[f"  library({name})" for name in extra if name not in _NEVER_ATTACH],
        "})",
        "",
    ]
    if extra:
        installable = ", ".join(r_literal(name) for name in ["dplyr", "tidyr", *extra])
        lines += [
            "# None of these are part of base R. Install what is missing with:",
            f"#   install.packages(c({installable}))",
        ]
        held_back = sorted(name for name in extra if name in _NEVER_ATTACH)
        if held_back:
            lines.append(
                f"# {', '.join(held_back)} is installed but deliberately not attached — it masks a"
            )
            lines.append("# function this script calls — so it is used as pkg::fn() below.")
        lines.append("")
    lines += [
        "# The product sorts group labels by Unicode code point (Python's sorted()).",
        "# R's sort() follows the collation locale, so pin it to C to get the same",
        "# order — otherwise the sign of a reported difference can flip.",
        'Sys.setlocale("LC_COLLATE", "C")',
        "",
    ]
    for helper in helpers_for(ops):
        lines += _helper_source(helper).split("\n") + [""]
    lines += [
        "# Load the data. Edit this line to point at your own file.",
        r_load_statement(source),
    ]
    return lines


def filter_block(spec_filter: dict[str, Any] | None) -> Lines:
    """The spec's row filter, matching ``analysis_executor.apply_filter`` row for row."""
    if not spec_filter:
        return [
            "",
            "# No filter was applied; every operation ran over the whole file.",
            f"{DATA} <- {FRAME}",
        ]

    column = r_literal(spec_filter["column"])
    operator = spec_filter["operator"]
    value = spec_filter.get("value")
    series = f"{FRAME}[[{column}]]"
    lines = ["", f"# Filter: {r_comment_text(spec_filter['column'])} {operator} {value!r}"]

    if operator == "is_null":
        lines.append(f"mask <- is.na({series})")
    elif operator == "is_not_null":
        lines.append(f"mask <- !is.na({series})")
    elif operator in ("contains", "not_contains"):
        lines += [
            "# The value is a regular expression, as it is in the product. Python's re",
            "# and R's POSIX engine agree on plain substrings; complex patterns may not.",
            f"text <- as.character({series})",
            f"hit <- !is.na(text) & grepl({r_literal(str(value))}, text, ignore.case = TRUE)",
            f"mask <- {'!hit' if operator == 'not_contains' else 'hit'}",
        ]
    elif operator in (">", ">=", "<", "<="):
        lines += [
            f"threshold <- num({r_literal(value)})",
            f"mask <- num({series}) {operator} threshold",
        ]
    elif operator == "==":
        lines.append(f"mask <- !is.na({series}) & {series} == {r_literal(value)}")
    else:  # "!="
        lines.append("# A missing value is not equal to anything, so it passes — as in pandas.")
        lines.append(f"mask <- is.na({series}) | {series} != {r_literal(value)}")

    lines += [
        "mask[is.na(mask)] <- FALSE",
        f"{DATA} <- {FRAME}[mask, , drop = FALSE]",
        f'cat(sprintf("Filtered to %d of %d rows.\\n", nrow({DATA}), nrow({FRAME})))',
    ]
    return lines


# ---------------------------------------------------------------------------
# Tier 1 — descriptive and aggregation
# ---------------------------------------------------------------------------


@_emits("describe")
def _emit_describe(params: dict[str, Any], label: str, index: int) -> Lines:
    columns = params.get("columns")
    chosen = (
        r_literal(list(columns))
        if columns
        else f"names({DATA})[vapply({DATA}, is.numeric, logical(1))]"
    )
    return [
        "# One row per column; the product prints the transpose of this table.",
        f"columns_{index} <- {chosen}",
        f"result_{index} <- do.call(rbind, lapply(columns_{index}, function(name) {{",
        f"  values <- num({DATA}[[name]])",
        "  values <- values[!is.na(values)]",
        "  data.frame(",
        "    column = name,",
        "    count = length(values),",
        "    mean = mean(values),",
        "    sd = sd(values),",
        "    min = min(values),",
        '    "25%" = quantile(values, 0.25, names = FALSE),',
        '    "50%" = quantile(values, 0.50, names = FALSE),',
        '    "75%" = quantile(values, 0.75, names = FALSE),',
        "    max = max(values),",
        "    check.names = FALSE, stringsAsFactors = FALSE",
        "  )",
        "}))",
        f"show_result({r_literal(label)}, result_{index})",
    ]


_R_AGGREGATIONS = {
    "sum": "sum(values, na.rm = TRUE)",
    "mean": "mean(values, na.rm = TRUE)",
    "median": "median(values, na.rm = TRUE)",
    "min": "min(values, na.rm = TRUE)",
    "max": "max(values, na.rm = TRUE)",
    "std": "sd(values, na.rm = TRUE)",
    "var": "var(values, na.rm = TRUE)",
    # count is pandas' non-null count within the group, not the row count.
    "count": "sum(!is.na(values))",
    "nunique": "dplyr::n_distinct(values[!is.na(values)])",
}


def _r_aggregate(agg: str, column: str, *, numeric: bool) -> str:
    """The summarise() expression for one aggregation over one column."""
    values = f"num(.data[[{column}]])" if numeric else f".data[[{column}]]"
    return _R_AGGREGATIONS[agg].replace("values", values)


@_emits("groupby_aggregate")
def _emit_groupby_aggregate(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by = r_literal(list(params["group_by"]))
    column, agg = params["column"], params["agg"]
    numeric = agg not in ("count", "nunique")
    lines = [
        f"subset_{index} <- {DATA} %>%",
        f"  filter(if_all(all_of({group_by}), ~ !is.na(.x)))",
    ]
    if numeric:
        lines += [
            "# count and nunique are meaningful over nulls; the numeric aggregations",
            "# are not, so only those drop rows missing the target column.",
            f"subset_{index} <- subset_{index} %>% filter(!is.na(.data[[{r_literal(column)}]]))",
        ]
    lines += [
        f"result_{index} <- subset_{index} %>%",
        f"  group_by(across(all_of({group_by}))) %>%",
        f"  summarise(.value = {_r_aggregate(agg, r_literal(column), numeric=numeric)},"
        ' .groups = "drop") %>%',
        "  arrange(desc(.value))",
        f"names(result_{index})[ncol(result_{index})] <- {r_literal(f'{column}_{agg}')}",
        f"show_result({r_literal(label)}, result_{index})",
    ]
    return lines


@_emits("value_counts")
def _emit_value_counts(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    top_n = r_literal(int(params.get("top_n", DEFAULT_VALUE_COUNTS)))
    normalize = bool(params.get("normalize", False))
    lines = [
        "# Ties are ordered by label here and by first appearance in pandas, so a",
        "# tied tail can come back in a different order with the same counts.",
        f"counted_{index} <- {DATA} %>%",
        f"  filter(!is.na(.data[[{column}]])) %>%",
        f'  count(across(all_of({column})), sort = TRUE, name = "count")',
    ]
    if normalize:
        lines += [
            "# Proportions are over every non-null row, then the head is taken —",
            "# taking the head first would renormalize to the wrong denominator.",
            f"counted_{index}$proportion <- counted_{index}$count / sum(counted_{index}$count)",
            f'result_{index} <- head(counted_{index}[, c({column}, "proportion")], {top_n})',
        ]
    else:
        lines.append(f"result_{index} <- head(counted_{index}, {top_n})")
    lines.append(f"show_result({r_literal(label)}, result_{index})")
    return lines


@_emits("crosstab")
def _emit_crosstab(params: dict[str, Any], label: str, index: int) -> Lines:
    row, column = _q(params, "row"), _q(params, "column")
    normalize = bool(params.get("normalize", False))
    lines = [
        f"counts_{index} <- table({DATA}[[{row}]], {DATA}[[{column}]])",
        "# Both R and scipy apply Yates' continuity correction to a 2x2 table by",
        "# default, so this statistic matches the product's without adjustment.",
        f"test_{index} <- suppressWarnings(chisq.test(counts_{index}))",
        f"stats_{index} <- list(",
        '  test = "chi-square test of independence",',
        f"  chi2 = round(unname(test_{index}$statistic), 4),",
        f"  p_value = round(test_{index}$p.value, 6),",
        f"  dof = as.integer(test_{index}$parameter)",
        ")",
    ]
    table = f"prop.table(counts_{index}, 1)" if normalize else f"counts_{index}"
    lines += [
        f"shown_{index} <- as.data.frame.matrix({table})",
        f"result_{index} <- cbind(",
        f"  setNames(data.frame(rownames(shown_{index}), stringsAsFactors = FALSE), {row}),",
        f"  shown_{index}",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]
    return lines


@_emits("histogram")
def _emit_histogram(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    bins = r_literal(int(params.get("bins", DEFAULT_BINS)))
    return [
        f"values_{index} <- num({DATA}[[{column}]])",
        f"values_{index} <- values_{index}[!is.na(values_{index})]",
        f"edges_{index} <- seq(min(values_{index}), max(values_{index}), length.out = {bins} + 1)",
        "# right = FALSE with include.lowest = TRUE gives half-open bins with a closed",
        "# final bin — exactly numpy.histogram's convention.",
        f"binned_{index} <- cut(values_{index}, breaks = edges_{index},"
        " include.lowest = TRUE, right = FALSE)",
        f"result_{index} <- data.frame(",
        f'  bin = sprintf("%.4g \\u2013 %.4g", head(edges_{index}, -1), tail(edges_{index}, -1)),',
        f"  count = as.integer(table(binned_{index})),",
        "  stringsAsFactors = FALSE",
        ")",
        f"show_result({r_literal(label)}, result_{index})",
    ]


@_emits("top_n")
def _emit_top_n(params: dict[str, Any], label: str, index: int) -> Lines:
    column, by = _q(params, "column"), _q(params, "by")
    n = r_literal(int(params.get("n", DEFAULT_TOP_N)))
    order = f".data[[{by}]]" if params.get("ascending", False) else f"desc(.data[[{by}]])"
    return [
        "# pandas' sort is not stable, so rows tied on the sort column can come back",
        "# in a different order here with the same values.",
        f"result_{index} <- {DATA} %>%",
        f"  filter(!is.na(.data[[{by}]])) %>%",
        f"  select(all_of(unique(c({column}, {by})))) %>%",
        f"  arrange({order}) %>%",
        f"  head({n})",
        f"show_result({r_literal(label)}, result_{index})",
    ]


@_emits("pivot")
def _emit_pivot(params: dict[str, Any], label: str, index: int) -> Lines:
    index_columns = r_literal(list(params["index"]))
    columns, values = _q(params, "columns"), _q(params, "values")
    agg = params["agg"]
    return [
        "# pandas sorts the resulting column headers; pivot_wider keeps them in the",
        "# order the categories first appear.",
        f"result_{index} <- {DATA} %>%",
        f"  filter(if_all(all_of(c({index_columns}, {columns})), ~ !is.na(.x))) %>%",
        f"  group_by(across(all_of(c({index_columns}, {columns})))) %>%",
        f"  summarise(.value = {_r_aggregate(agg, values, numeric=agg not in ('count', 'nunique'))},"
        ' .groups = "drop") %>%',
        f'  tidyr::pivot_wider(names_from = all_of({columns}), values_from = ".value") %>%',
        f"  arrange(across(all_of({index_columns})))",
        f"show_result({r_literal(label)}, result_{index})",
    ]


_R_RESAMPLE_UNITS = {"D": "day", "W": "week", "ME": "month", "QE": "quarter", "YE": "year"}


@_emits("resample")
def _emit_resample(params: dict[str, Any], label: str, index: int) -> Lines:
    date_column, column = _q(params, "date_column"), _q(params, "column")
    agg = params["agg"]
    unit = _R_RESAMPLE_UNITS.get(str(params["freq"]), "month")
    return [
        "# Two differences worth knowing about, neither of which changes a value:",
        "# pandas labels each bucket by the END of its period and cut() by the start,",
        "# and pandas emits empty periods (sum = 0) where R omits them entirely.",
        '# pandas week buckets end on Sunday; cut(breaks = "week") starts them on Monday.',
        f"subset_{index} <- {DATA} %>%",
        f"  filter(!is.na(.data[[{date_column}]]), !is.na(.data[[{column}]]))",
        f"period_{index} <- as.Date(cut(as.Date(subset_{index}[[{date_column}]]),"
        f' breaks = "{unit}"))',
        f"result_{index} <- data.frame(",
        f"  period = period_{index},",
        f"  value = num(subset_{index}[[{column}]]),",
        "  stringsAsFactors = FALSE",
        ") %>%",
        "  group_by(period) %>%",
        f"  summarise(.value = {_R_AGGREGATIONS[agg].replace('values', 'value')},"
        ' .groups = "drop")',
        f"names(result_{index}) <- c({date_column}, {r_literal(f'{params["column"]}_{agg}')})",
        f"show_result({r_literal(label)}, result_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 2 — bivariate
# ---------------------------------------------------------------------------


@_emits("correlation_matrix")
def _emit_correlation_matrix(params: dict[str, Any], label: str, index: int) -> Lines:
    columns = r_literal(list(params["columns"]))
    method = r_literal(params.get("method", "pearson"))
    return [
        f"columns_{index} <- {columns}",
        f"subset_{index} <- {DATA}[, columns_{index}, drop = FALSE]",
        f"subset_{index}[] <- lapply(subset_{index}, num)",
        f"subset_{index} <- subset_{index}[complete.cases(subset_{index}), , drop = FALSE]",
        f"matrix_{index} <- round(cor(subset_{index}, method = {method}), 4)",
        f"result_{index} <- cbind(",
        f"  data.frame(column = rownames(matrix_{index}), stringsAsFactors = FALSE),",
        f"  as.data.frame(matrix_{index})",
        ")",
        "# R and scipy choose between exact and asymptotic p-values by different rules",
        "# for the rank correlations. The coefficient always matches; for spearman and",
        "# kendall pass exact = FALSE to get the asymptotic p-value scipy reports.",
        f"pairs_{index} <- list()",
        f"for (a_i in seq_along(columns_{index})) {{",
        f"  for (b_i in seq_len(length(columns_{index}) - a_i) + a_i) {{",
        f"    x_name <- columns_{index}[a_i]",
        f"    y_name <- columns_{index}[b_i]",
        "    test <- suppressWarnings(cor.test(",
        f"      subset_{index}[[x_name]], subset_{index}[[y_name]], method = {method}",
        "    ))",
        f"    pairs_{index}[[length(pairs_{index}) + 1]] <- data.frame(",
        "      x = x_name, y = y_name,",
        "      r = round(unname(test$estimate), 4),",
        "      p_value = round(test$p.value, 6),",
        "      stringsAsFactors = FALSE",
        "    )",
        "  }",
        "}",
        f"stats_{index} <- list(method = {method})",
        f"print(do.call(rbind, pairs_{index}))",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("scatter_with_fit")
def _emit_scatter_with_fit(params: dict[str, Any], label: str, index: int) -> Lines:
    x, y = _q(params, "x"), _q(params, "y")
    return [
        f"points_{index} <- data.frame(",
        f"  x = num({DATA}[[{x}]]),",
        f"  y = num({DATA}[[{y}]]),",
        "  stringsAsFactors = FALSE",
        ")",
        f"points_{index} <- points_{index}[complete.cases(points_{index}), , drop = FALSE]",
        f"fit_{index} <- lm(y ~ x, data = points_{index})",
        f"summary_{index} <- summary(fit_{index})",
        f"result_{index} <- setNames(points_{index}, c({x}, {y}))",
        f"stats_{index} <- list(",
        f"  slope = round(unname(coef(fit_{index})[2]), 6),",
        f"  intercept = round(unname(coef(fit_{index})[1]), 6),",
        f"  r = round(sqrt(summary_{index}$r.squared) * sign(coef(fit_{index})[2]), 4),",
        f"  r_squared = round(summary_{index}$r.squared, 4),",
        f"  p_value = round(summary_{index}$coefficients[2, 4], 6),",
        f"  std_err = round(summary_{index}$coefficients[2, 2], 6)",
        ")",
        f"show_result({r_literal(label)}, head(result_{index}), stats_{index})",
    ]


@_emits("group_comparison", "split_groups")
def _emit_group_comparison(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"pair_{index} <- split_groups({DATA}, {group_by}, {column})",
        f"groups_{index} <- split(pair_{index}$value, pair_{index}$group)",
        "# A 95% interval on each group mean: bare means do not show whether the",
        "# groups are distinguishable, which is the point of a comparison.",
        f"result_{index} <- do.call(rbind, lapply(names(groups_{index}), function(label) {{",
        f"  values <- groups_{index}[[label]]",
        "  spread <- if (length(values) > 1) sd(values) else NA_real_",
        "  usable <- length(values) > 1 && !is.na(spread) && spread > 0",
        "  margin <- if (usable)",
        "    qt(0.975, length(values) - 1) * spread / sqrt(length(values)) else NA_real_",
        "  data.frame(",
        "    label = label,",
        "    count = length(values),",
        "    mean = mean(values),",
        "    std = spread,",
        "    median = median(values),",
        "    ci95_low = if (usable) round(mean(values) - margin, 4) else NA_real_,",
        "    ci95_high = if (usable) round(mean(values) + margin, 4) else NA_real_,",
        "    stringsAsFactors = FALSE",
        "  )",
        "}))",
        f"names(result_{index})[1] <- {group_by}",
        f"usable_{index} <- groups_{index}[lengths(groups_{index}) > 1]",
        f"stats_{index} <- list()",
        f"if (length(usable_{index}) == 2) {{",
        f"  test_{index} <- t.test(usable_{index}[[1]], usable_{index}[[2]], var.equal = FALSE)",
        f"  stats_{index} <- list(",
        '    test = "Welch\'s t-test (two groups, unequal variance)",',
        f"    statistic = round(unname(test_{index}$statistic), 4),",
        f"    p_value = round(test_{index}$p.value, 6)",
        "  )",
        f"}} else if (length(usable_{index}) > 2) {{",
        f"  long_{index} <- data.frame(",
        f"    value = unlist(usable_{index}, use.names = FALSE),",
        f"    group = factor(rep(names(usable_{index}), lengths(usable_{index})))",
        "  )",
        f"  table_{index} <- summary(aov(value ~ group, data = long_{index}))[[1]]",
        f"  stats_{index} <- list(",
        '    test = "one-way ANOVA",',
        f'    statistic = round(table_{index}[["F value"]][1], 4),',
        f'    p_value = round(table_{index}[["Pr(>F)"]][1], 6)',
        "  )",
        "}",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 3 — inferential
# ---------------------------------------------------------------------------

_R_ALTERNATIVES = {"two-sided": "two.sided", "less": "less", "greater": "greater"}

_LEVENE_NOTE = [
    "# Levene's test (median-centred, i.e. Brown-Forsythe) is not in base R, and",
    "# bartlett.test() is not a substitute because it assumes normality. Use:",
    '#   install.packages("car"); car::leveneTest(value ~ group, data = pair, center = median)',
]


def _r_alternative(params: dict[str, Any]) -> str:
    return r_literal(_R_ALTERNATIVES.get(str(params.get("alternative", "two-sided")), "two.sided"))


def _emit_r_ttest_one_sample(params: dict[str, Any], label: str, index: int) -> Lines:
    column, mu = _q(params, "column"), r_literal(float(params["mu"]))
    return [
        f"values_{index} <- num({DATA}[[{column}]])",
        f"values_{index} <- values_{index}[!is.na(values_{index})]",
        f"test_{index} <- t.test(values_{index}, mu = {mu},"
        f" alternative = {_r_alternative(params)})",
        f"bounds_{index} <- mean_ci(values_{index})",
        f"result_{index} <- data.frame(",
        f"  measure = {column},",
        f"  n = length(values_{index}),",
        f"  mean = mean(values_{index}),",
        f"  sd = sd(values_{index}),",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        f"  tested_against = {mu},",
        "  stringsAsFactors = FALSE",
        ")",
        f"stats_{index} <- list(",
        f"  statistic = unname(test_{index}$statistic),",
        f"  dof = unname(test_{index}$parameter),",
        f"  p_value = test_{index}$p.value,",
        f"  mean_difference = mean(values_{index}) - {mu},",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        f"  effect_size = (mean(values_{index}) - {mu}) / sd(values_{index}),",
        f"  normality_p = normality_p(values_{index})",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_r_ttest_independent(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    equal_var = r_literal(bool(params.get("equal_var", False)))
    return [
        f"pair_{index} <- split_groups({DATA}, {group_by}, {column})",
        f"groups_{index} <- split(pair_{index}$value, pair_{index}$group)",
        f"first_{index} <- groups_{index}[[1]]",
        f"second_{index} <- groups_{index}[[2]]",
        f"test_{index} <- t.test(",
        f"  first_{index}, second_{index},",
        f"  var.equal = {equal_var}, alternative = {_r_alternative(params)}",
        ")",
        "# The interval is computed separately so a one-sided test still reports the",
        "# two-sided interval the product reports.",
        f"bounds_{index} <- mean_difference_ci("
        f"first_{index}, second_{index}, equal_var = {equal_var})",
        f"effect_{index} <- cohens_d(first_{index}, second_{index})",
        f"result_{index} <- group_summary(pair_{index}, {group_by})",
        f"stats_{index} <- list(",
        f'  comparison = paste(levels(pair_{index}$group)[1], "minus",'
        f" levels(pair_{index}$group)[2]),",
        f"  statistic = unname(test_{index}$statistic),",
        f"  dof = unname(test_{index}$parameter),",
        f"  p_value = test_{index}$p.value,",
        f"  mean_difference = mean(first_{index}) - mean(second_{index}),",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        f"  effect_size = effect_{index}[1],",
        f"  hedges_g = effect_{index}[2],",
        f"  normality_p = vapply(groups_{index}, normality_p, numeric(1))",
        ")",
        *_LEVENE_NOTE,
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_r_ttest_paired(params: dict[str, Any], label: str, index: int) -> Lines:
    column, column2 = _q(params, "column"), _q(params, "column2")
    return [
        f"pair_{index} <- data.frame(",
        f"  a = num({DATA}[[{column}]]),",
        f"  b = num({DATA}[[{column2}]]),",
        "  stringsAsFactors = FALSE",
        ")",
        f"pair_{index} <- pair_{index}[complete.cases(pair_{index}), , drop = FALSE]",
        f"differences_{index} <- pair_{index}$a - pair_{index}$b",
        f"test_{index} <- t.test(pair_{index}$a, pair_{index}$b, paired = TRUE,"
        f" alternative = {_r_alternative(params)})",
        f"bounds_{index} <- mean_ci(differences_{index})",
        f"result_{index} <- data.frame(",
        f'  measure = c({column}, {column2}, "difference"),',
        f"  n = nrow(pair_{index}),",
        f"  mean = c(mean(pair_{index}$a), mean(pair_{index}$b), mean(differences_{index})),",
        "  stringsAsFactors = FALSE",
        ")",
        f"stats_{index} <- list(",
        f"  statistic = unname(test_{index}$statistic),",
        f"  dof = unname(test_{index}$parameter),",
        f"  p_value = test_{index}$p.value,",
        f"  mean_difference = mean(differences_{index}),",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        f"  effect_size = mean(differences_{index}) / sd(differences_{index}),",
        f"  normality_p = normality_p(differences_{index})",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


_R_TTEST_KINDS = {
    "one_sample": _emit_r_ttest_one_sample,
    "independent": _emit_r_ttest_independent,
    "paired": _emit_r_ttest_paired,
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
def _emit_r_ttest(params: dict[str, Any], label: str, index: int) -> Lines:
    kind = str(params.get("kind"))
    emitter = _R_TTEST_KINDS.get(kind)
    if emitter is None:  # pragma: no cover - validation rejects this first
        return [f"# ttest: unknown kind {r_comment_text(kind)}; no code emitted."]
    return [f"# {kind.replace('_', '-')} t-test"] + emitter(params, label, index)


@_emits("anova", "split_groups", "mean_ci", "group_summary", "normality_p")
def _emit_r_anova(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"pair_{index} <- split_groups({DATA}, {group_by}, {column})",
        f"fit_{index} <- aov(value ~ group, data = pair_{index})",
        f"table_{index} <- summary(fit_{index})[[1]]",
        f'ss_between_{index} <- table_{index}[["Sum Sq"]][1]',
        f'ss_within_{index} <- table_{index}[["Sum Sq"]][2]',
        f'df_between_{index} <- table_{index}[["Df"]][1]',
        f'df_within_{index} <- table_{index}[["Df"]][2]',
        f"ms_within_{index} <- ss_within_{index} / df_within_{index}",
        f"ss_total_{index} <- ss_between_{index} + ss_within_{index}",
        f"result_{index} <- group_summary(pair_{index}, {group_by})",
        f"stats_{index} <- list(",
        f'  statistic = table_{index}[["F value"]][1],',
        f"  df_between = df_between_{index},",
        f"  df_within = df_within_{index},",
        f'  p_value = table_{index}[["Pr(>F)"]][1],',
        f"  effect_size = ss_between_{index} / ss_total_{index},",
        f"  omega_squared = (ss_between_{index} - df_between_{index} * ms_within_{index}) /",
        f"    (ss_total_{index} + ms_within_{index}),",
        f"  normality_p = vapply(split(pair_{index}$value, pair_{index}$group),"
        " normality_p, numeric(1))",
        ")",
        *_LEVENE_NOTE,
        "# Running every pairwise t-test after a significant F is the classic way to",
        "# manufacture a false positive; Tukey's HSD adjusts for how many are made.",
        f"print(TukeyHSD(fit_{index}))",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("kruskal", "split_groups", "rank_summary")
def _emit_r_kruskal(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"pair_{index} <- split_groups({DATA}, {group_by}, {column})",
        f"test_{index} <- kruskal.test(value ~ group, data = pair_{index})",
        f"k_{index} <- nlevels(pair_{index}$group)",
        f"n_{index} <- nrow(pair_{index})",
        f"result_{index} <- rank_summary(pair_{index}, {group_by})",
        f"stats_{index} <- list(",
        f"  statistic = unname(test_{index}$statistic),",
        f"  dof = unname(test_{index}$parameter),",
        f"  p_value = test_{index}$p.value,",
        "  # Epsilon squared: the rank analogue of eta squared.",
        f"  effect_size = (unname(test_{index}$statistic) - k_{index} + 1) /"
        f" (n_{index} - k_{index})",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("mannwhitney", "split_groups", "rank_summary")
def _emit_r_mannwhitney(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by, column = _q(params, "group_by"), _q(params, "column")
    return [
        f"pair_{index} <- split_groups({DATA}, {group_by}, {column})",
        f"groups_{index} <- split(pair_{index}$value, pair_{index}$group)",
        f"first_{index} <- groups_{index}[[1]]",
        f"second_{index} <- groups_{index}[[2]]",
        "# exact = FALSE, correct = TRUE is scipy's asymptotic branch, which scipy uses",
        "# whenever a group reaches 8 observations or there are ties. Drop it for a",
        "# tiny, tie-free sample, where scipy uses the exact distribution instead.",
        f"test_{index} <- suppressWarnings(wilcox.test(",
        f"  first_{index}, second_{index}, alternative = {_r_alternative(params)},",
        "  exact = FALSE, correct = TRUE",
        "))",
        "# The median of all pairwise differences. wilcox.test(conf.int = TRUE)$estimate",
        "# is R's own Hodges-Lehmann estimate and can differ in the last digits.",
        f'shift_{index} <- median(outer(first_{index}, second_{index}, "-"))',
        f"result_{index} <- rank_summary(pair_{index}, {group_by})",
        f"stats_{index} <- list(",
        f'  comparison = paste(levels(pair_{index}$group)[1], "minus",'
        f" levels(pair_{index}$group)[2]),",
        f"  statistic = unname(test_{index}$statistic),",
        f"  p_value = test_{index}$p.value,",
        f"  median_difference = median(first_{index}) - median(second_{index}),",
        f"  hodges_lehmann_shift = shift_{index},",
        "  # Rank-biserial correlation, signed so a negative value means the first",
        "  # group ranks below the second.",
        f"  effect_size = 2 * unname(test_{index}$statistic) /"
        f" (length(first_{index}) * length(second_{index})) - 1",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("wilcoxon")
def _emit_r_wilcoxon(params: dict[str, Any], label: str, index: int) -> Lines:
    column, column2 = _q(params, "column"), _q(params, "column2")
    two_sided = str(params.get("alternative", "two-sided")) == "two-sided"
    statistic = f"min(w_plus_{index}, w_minus_{index})" if two_sided else f"w_plus_{index}"
    return [
        f"pair_{index} <- data.frame(",
        f"  a = num({DATA}[[{column}]]),",
        f"  b = num({DATA}[[{column2}]]),",
        "  stringsAsFactors = FALSE",
        ")",
        f"pair_{index} <- pair_{index}[complete.cases(pair_{index}), , drop = FALSE]",
        f"differences_{index} <- pair_{index}$a - pair_{index}$b",
        "# See the note on mannwhitney: this is scipy's asymptotic branch.",
        f"test_{index} <- suppressWarnings(wilcox.test(",
        f"  pair_{index}$a, pair_{index}$b, paired = TRUE, alternative = {_r_alternative(params)},",
        "  exact = FALSE, correct = TRUE",
        "))",
        f"nonzero_{index} <- differences_{index}[differences_{index} != 0]",
        f"ranks_{index} <- rank(abs(nonzero_{index}))",
        f"w_plus_{index} <- sum(ranks_{index}[nonzero_{index} > 0])",
        f"w_minus_{index} <- sum(ranks_{index}[nonzero_{index} < 0])",
        "# R's wilcox.test reports V = W+; scipy reports min(W+, W-) for a two-sided",
        "# test and W+ otherwise, so the product's statistic is recomputed here.",
        f"result_{index} <- data.frame(",
        f'  measure = c({column}, {column2}, "difference"),',
        f"  n = nrow(pair_{index}),",
        f"  median = c(median(pair_{index}$a), median(pair_{index}$b),"
        f" median(differences_{index})),",
        "  stringsAsFactors = FALSE",
        ")",
        f"stats_{index} <- list(",
        f"  statistic = {statistic},",
        f"  p_value = test_{index}$p.value,",
        f"  n_pairs = nrow(pair_{index}),",
        f"  median_difference = median(differences_{index}),",
        "  # Matched-pairs rank-biserial: the rank-weighted balance of signs.",
        f"  effect_size = (w_plus_{index} - w_minus_{index}) / sum(ranks_{index})",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_r_chi_square_independence(params: dict[str, Any], label: str, index: int) -> Lines:
    row, column = _q(params, "row"), _q(params, "column")
    return [
        f"frame_{index} <- {DATA}[",
        f"  !is.na({DATA}[[{row}]]) & !is.na({DATA}[[{column}]]), , drop = FALSE",
        "]",
        f"observed_{index} <- table(frame_{index}[[{row}]], frame_{index}[[{column}]])",
        "# An all-zero row or column carries no information and makes the test",
        "# undefined, so it is dropped rather than left to raise.",
        f"observed_{index} <- observed_{index}[",
        f"  rowSums(observed_{index}) > 0, colSums(observed_{index}) > 0, drop = FALSE",
        "]",
        f"corrected_{index} <- suppressWarnings(chisq.test(observed_{index}))",
        f"uncorrected_{index} <- suppressWarnings(chisq.test(observed_{index}, correct = FALSE))",
        f"total_{index} <- sum(observed_{index})",
        f"smaller_{index} <- min(nrow(observed_{index}) - 1, ncol(observed_{index}) - 1)",
        f"shown_{index} <- as.data.frame.matrix(observed_{index})",
        f"result_{index} <- cbind(",
        f"  setNames(data.frame(rownames(shown_{index}), stringsAsFactors = FALSE), {row}),",
        f"  shown_{index}",
        ")",
        f"stats_{index} <- list(",
        f"  statistic = unname(corrected_{index}$statistic),",
        f"  dof = as.integer(corrected_{index}$parameter),",
        f"  p_value = corrected_{index}$p.value,",
        f"  continuity_correction = all(dim(observed_{index}) == c(2, 2)),",
        "  # Cramer's V comes from the uncorrected statistic by convention: the",
        "  # continuity correction exists to fix the p-value, not the effect size.",
        f"  effect_size = sqrt(unname(uncorrected_{index}$statistic) /"
        f" (total_{index} * smaller_{index})),",
        f"  smallest_expected_count = min(corrected_{index}$expected)",
        ")",
        f"if (all(dim(observed_{index}) == c(2, 2))) {{",
        "  # fisher.test reports the CONDITIONAL MLE odds ratio; the product reports",
        "  # the sample odds ratio ad/bc, which scipy's fisher_exact returns. Both are",
        "  # given here because they are genuinely different numbers.",
        f"  exact_{index} <- fisher.test(observed_{index})",
        f"  stats_{index}$fisher_odds_ratio <- (observed_{index}[1, 1] * observed_{index}[2, 2]) /",
        f"    (observed_{index}[1, 2] * observed_{index}[2, 1])",
        f"  stats_{index}$fisher_conditional_odds_ratio <- unname(exact_{index}$estimate)",
        f"  stats_{index}$fisher_p_value <- exact_{index}$p.value",
        "}",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_r_chi_square_goodness_of_fit(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    return [
        "# Tested against a uniform distribution — equal counts in every category.",
        "# The pipeline does not accept a hypothesized distribution from the model,",
        "# because the model does not supply numbers.",
        f"present_{index} <- as.character({DATA}[[{column}]])",
        f"present_{index} <- present_{index}[!is.na(present_{index})]",
        f"counts_{index} <- table(present_{index})",
        f"counts_{index} <- counts_{index}[order(names(counts_{index}))]",
        f"total_{index} <- sum(counts_{index})",
        f"expected_{index} <- total_{index} / length(counts_{index})",
        f"test_{index} <- chisq.test(as.integer(counts_{index}))",
        f"result_{index} <- data.frame(",
        f"  category = names(counts_{index}),",
        f"  observed = as.integer(counts_{index}),",
        f"  expected = expected_{index},",
        "  stringsAsFactors = FALSE",
        ")",
        f"names(result_{index})[1] <- {column}",
        f"stats_{index} <- list(",
        f"  statistic = unname(test_{index}$statistic),",
        f"  dof = as.integer(test_{index}$parameter),",
        f"  p_value = test_{index}$p.value,",
        f"  expected_per_category = expected_{index},",
        "  # Cohen's w.",
        f"  effect_size = sqrt(unname(test_{index}$statistic) / total_{index})",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("chi_square")
def _emit_r_chi_square(params: dict[str, Any], label: str, index: int) -> Lines:
    if str(params.get("kind")) == "goodness_of_fit":
        return _emit_r_chi_square_goodness_of_fit(params, label, index)
    return _emit_r_chi_square_independence(params, label, index)


_R_Z_TAIL = {
    "two-sided": "2 * pnorm(abs({z}), lower.tail = FALSE)",
    "greater": "pnorm({z}, lower.tail = FALSE)",
    "less": "pnorm({z})",
}

_PROP_TEST_NOTE = [
    "# prop.test() is not used: it applies a continuity correction by default and",
    "# reports a chi-square rather than the z the product reports. The arithmetic is",
    "# short enough to write out, and writing it out is what makes it checkable.",
]


def _r_z_p_value(params: dict[str, Any], variable: str) -> str:
    alternative = str(params.get("alternative", "two-sided"))
    return _R_Z_TAIL.get(alternative, _R_Z_TAIL["two-sided"]).format(z=variable)


def _emit_r_proportion_one_sample(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    success = r_literal(str(params["success_value"]))
    p0 = r_literal(float(params["p0"]))
    return [
        *_PROP_TEST_NOTE,
        f"present_{index} <- {DATA}[[{column}]]",
        f"present_{index} <- as.character(present_{index}[!is.na(present_{index})])",
        f"successes_{index} <- sum(present_{index} == {success})",
        f"n_{index} <- length(present_{index})",
        f"proportion_{index} <- successes_{index} / n_{index}",
        f"se_{index} <- sqrt({p0} * (1 - {p0}) / n_{index})",
        f"z_{index} <- (proportion_{index} - {p0}) / se_{index}",
        f"bounds_{index} <- wilson_ci(successes_{index}, n_{index})",
        f"result_{index} <- data.frame(",
        f"  category = {success},",
        f"  n = n_{index},",
        f"  successes = successes_{index},",
        f"  proportion = proportion_{index},",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        f"  tested_against = {p0},",
        "  stringsAsFactors = FALSE",
        ")",
        f"names(result_{index})[1] <- {column}",
        f"stats_{index} <- list(",
        f"  statistic = z_{index},",
        f"  p_value = {_r_z_p_value(params, f'z_{index}')},",
        f"  proportion = proportion_{index},",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        "  # Cohen's h, on the arcsine scale.",
        f"  effect_size = 2 * asin(sqrt(proportion_{index})) - 2 * asin(sqrt({p0}))",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


def _emit_r_proportion_two_sample(params: dict[str, Any], label: str, index: int) -> Lines:
    column, group_by = _q(params, "column"), _q(params, "group_by")
    success = r_literal(str(params["success_value"]))
    return [
        *_PROP_TEST_NOTE,
        f"frame_{index} <- {DATA}[",
        f"  !is.na({DATA}[[{group_by}]]) & !is.na({DATA}[[{column}]]), , drop = FALSE",
        "]",
        f"labels_{index} <- sort(unique(as.character(frame_{index}[[{group_by}]])))",
        f"counts_{index} <- lapply(labels_{index}, function(label) {{",
        f"  values <- as.character(frame_{index}[",
        f"    as.character(frame_{index}[[{group_by}]]) == label, {column}",
        "  ])",
        f"  c(sum(values == {success}), length(values))",
        "})",
        f"successes1_{index} <- counts_{index}[[1]][1]; n1_{index} <- counts_{index}[[1]][2]",
        f"successes2_{index} <- counts_{index}[[2]][1]; n2_{index} <- counts_{index}[[2]][2]",
        f"p1_{index} <- successes1_{index} / n1_{index}",
        f"p2_{index} <- successes2_{index} / n2_{index}",
        f"pooled_{index} <- (successes1_{index} + successes2_{index}) / (n1_{index} + n2_{index})",
        f"se_{index} <- sqrt(pooled_{index} * (1 - pooled_{index}) *"
        f" (1 / n1_{index} + 1 / n2_{index}))",
        f"z_{index} <- (p1_{index} - p2_{index}) / se_{index}",
        f"bounds_{index} <- proportion_difference_ci(",
        f"  successes1_{index}, n1_{index}, successes2_{index}, n2_{index}",
        ")",
        f"result_{index} <- do.call(rbind, Map(function(label, pair) {{",
        "  interval <- wilson_ci(pair[1], pair[2])",
        "  data.frame(",
        "    label = label, n = pair[2], successes = pair[1],",
        "    proportion = pair[1] / pair[2],",
        "    ci95_low = interval[1], ci95_high = interval[2],",
        "    stringsAsFactors = FALSE",
        "  )",
        f"}}, labels_{index}, counts_{index}))",
        f"names(result_{index})[1] <- {group_by}",
        f"stats_{index} <- list(",
        f'  comparison = paste(labels_{index}[1], "minus", labels_{index}[2]),',
        f"  statistic = z_{index},",
        f"  p_value = {_r_z_p_value(params, f'z_{index}')},",
        f"  difference = p1_{index} - p2_{index},",
        f"  ci95_low = bounds_{index}[1],",
        f"  ci95_high = bounds_{index}[2],",
        "  # Cohen's h, on the arcsine scale.",
        f"  effect_size = 2 * asin(sqrt(p1_{index})) - 2 * asin(sqrt(p2_{index}))",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@_emits("proportion_test", "wilson_ci", "proportion_difference_ci")
def _emit_r_proportion_test(params: dict[str, Any], label: str, index: int) -> Lines:
    if params.get("group_by") is not None:
        return _emit_r_proportion_two_sample(params, label, index)
    return _emit_r_proportion_one_sample(params, label, index)


_R_NORMALITY_ROW = [
    "normality_row <- function(values, label) {",
    "  p_value <- normality_p(values)",
    "  data.frame(",
    "    group = label,",
    "    n = length(values),",
    "    mean = mean(values),",
    "    sd = if (length(values) > 1) sd(values) else NA_real_,",
    "    skewness = if (length(values) > 2) skewness(values) else NA_real_,",
    "    kurtosis = if (length(values) > 3) kurtosis(values) else NA_real_,",
    "    shapiro_p = p_value,",
    f"    normal_at_0.05 = if (is.na(p_value)) NA else p_value >= {ALPHA!r},",
    "    check.names = FALSE, stringsAsFactors = FALSE",
    "  )",
    "}",
]


@_emits("normality_test", "split_groups", "normality_p", "shape_stats")
def _emit_r_normality_test(params: dict[str, Any], label: str, index: int) -> Lines:
    column = _q(params, "column")
    group_by = params.get("group_by")
    lines = list(_R_NORMALITY_ROW)
    lines += [
        "",
        "# The product also renders a prose verdict from these numbers; the numbers",
        "# themselves are what is reproduced here.",
    ]
    if group_by is None:
        lines += [
            f"values_{index} <- num({DATA}[[{column}]])",
            f"values_{index} <- values_{index}[!is.na(values_{index})]",
            f'result_{index} <- normality_row(values_{index}, "(all rows)")',
        ]
    else:
        lines += [
            f"pair_{index} <- split_groups({DATA}, {r_literal(group_by)}, {column})",
            f"groups_{index} <- split(pair_{index}$value, pair_{index}$group)",
            f"groups_{index} <- groups_{index}[lengths(groups_{index}) >= 3]",
            f"result_{index} <- do.call(rbind, Map(normality_row, groups_{index},"
            f" names(groups_{index})))",
            f"names(result_{index})[1] <- {r_literal(group_by)}",
        ]
    lines.append(f"show_result({r_literal(label)}, result_{index})")
    return lines
