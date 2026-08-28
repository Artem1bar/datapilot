"""The exported code must produce the numbers the product reported.

This file is the reason the code-export feature is worth anything. A script
that *looks* like the analysis is a liability: a researcher who reruns it and
gets a different number learns that the product cannot be checked, which is
worse than never offering an export.

So the central test does not inspect the generated string. For every supported
operation it builds a frame, runs the real pipeline (``execute_spec``), renders
the Python export, executes that script against the same frame, and asserts the
result table and the headline statistics agree. The load line is substituted for
the in-memory frame; nothing else about the script is touched.

R cannot be executed unless ``Rscript`` is on PATH. When it is, the R export is
run and compared the same way; when it is not, the R tests fall back to
structural checks — literal escaping, bracket balance outside string literals,
and the presence of the idiomatic call for each operation.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.services.analysis_codegen import (
    NO_EQUIVALENT_MARKER,
    export_code,
    py_literal,
    python_load_statement,
    r_literal,
    r_load_statement,
    supported_operations,
    unsupported_operations,
)
from app.services.analysis_codegen_python import (
    DEFAULT_BINS,
    DEFAULT_TOP_N,
    DEFAULT_VALUE_COUNTS,
)
from app.services.analysis_executor import execute_spec
from app.services.analysis_result import MAX_RESULT_ROWS, OperationResult, to_python
from app.services.analysis_spec import OPERATIONS

RSCRIPT = shutil.which("Rscript")
requires_r = pytest.mark.skipif(RSCRIPT is None, reason="Rscript is not installed")

# Every registered operation is expected to have an emitter in both languages.
# TestCoverage pins that: a tier added without an export fails there rather than
# quietly emitting a "no code equivalent" comment nobody reads.
EXPORTED_OPS = frozenset(OPERATIONS)

# The generated script rounds nothing the product does not round, so agreement
# is expected to machine precision. The tolerance is here to absorb a different
# order of floating-point operations, not a different calculation.
TOLERANCE = 1e-6

# ARIMA, quantile regression and the negative binomial reach their estimates by
# iteration rather than by a closed form, so their agreement is not guaranteed
# by algebra. It is guaranteed by determinism: the export runs the same
# optimizer, from the same start, on the same rows, so the iterates are
# identical — measured agreement on the fixtures below is exact to double
# precision. The tolerance is therefore held at TOLERANCE rather than loosened;
# a looser one would stop catching a genuine change in how the model is fitted,
# which is the only thing this test exists to catch. If a future statsmodels
# changes an optimizer default, this is the assertion that should fail.
ITERATIVE_TOLERANCE = TOLERANCE


# ---------------------------------------------------------------------------
# Fixtures: an ordinary frame, and one whose column names are hostile
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    """A frame with every shape the operations need, and some missing values."""
    rng = np.random.default_rng(20260827)
    n = 150
    regions = np.array(["East", "North", "West"])
    segments = np.array(["Enterprise", "SMB"])

    revenue = rng.normal(1000, 250, n)
    cost = revenue * 0.6 + rng.normal(0, 60, n)
    before = rng.normal(50, 8, n)

    data = pd.DataFrame(
        {
            "region": regions[rng.integers(0, 3, n)],
            "segment": segments[rng.integers(0, 2, n)],
            "revenue": revenue,
            "cost": cost,
            "before": before,
            "after": before + rng.normal(2.5, 5, n),
            "converted": np.where(rng.random(n) < 0.42, "yes", "no"),
            "signup_date": pd.to_datetime("2025-01-01")
            + pd.to_timedelta(rng.integers(0, 600, n), unit="D"),
        }
    )
    # Missing values in three columns, so every exclusion path is exercised.
    data.loc[data.index[:4], "revenue"] = np.nan
    data.loc[data.index[10:13], "region"] = None
    data.loc[data.index[20:22], "after"] = np.nan
    return data


# A column name for every way a name can break generated source: a quote, an
# apostrophe, a backslash, a newline, non-ASCII, spaces, a Python builtin and a
# Python keyword. None of these may reach the emitted code as a bare identifier.
QUOTED = 'it\'s a "test"'
BACKSLASH = "back\\slash\\path"
NEWLINE = "line\nbreak"
UNICODE = "naïve café ☕"
SPACED = "has spaces"
BUILTIN = "sum"
KEYWORD = "class"
DATED = "when it\\happened"
ADVERSARIAL_COLUMNS = (QUOTED, BACKSLASH, NEWLINE, UNICODE, SPACED, BUILTIN, KEYWORD, DATED)


@pytest.fixture(scope="module")
def model_frame() -> pd.DataFrame:
    """A frame the Tier 4 and Tier 6 operations can actually be fitted on.

    Distinct from ``frame`` because a regression and a weighted estimate need
    things a descriptive fixture does not: a count outcome with a positive
    exposure, a categorical regressor with a stable alphabetical baseline, and a
    design with weights, strata and at least two primary sampling units in every
    stratum. Missing values in two columns so listwise deletion is exercised.
    """
    rng = np.random.default_rng(20260827)
    n = 180
    regions = np.array(["East", "North", "West"])
    region = regions[rng.integers(0, 3, n)]
    cost = rng.normal(600, 120, n)
    revenue = 300 + 1.4 * cost + np.where(region == "North", 120.0, 0.0) + rng.normal(0, 90, n)
    exposure = rng.uniform(0.5, 4.0, n)
    stratum = np.array(["A", "B", "C"])[rng.integers(0, 3, n)]

    data = pd.DataFrame(
        {
            "region": region,
            "segment": np.array(["Enterprise", "SMB"])[rng.integers(0, 2, n)],
            "revenue": revenue,
            "cost": cost,
            "orders": rng.poisson(np.clip(exposure * (2 + 0.002 * cost), 0.2, None)),
            "exposure": exposure,
            "converted": np.where(rng.random(n) < 0.42, "yes", "no"),
            # Lognormal weights: a realistic post-stratification spread, and one
            # that makes the weighted and unweighted estimates genuinely differ.
            "weight": np.exp(rng.normal(0, 0.5, n)) * 12,
            "stratum": stratum,
            "psu": np.array([f"{label}-{position % 6}" for position, label in enumerate(stratum)]),
        }
    )
    data.loc[data.index[:3], "revenue"] = np.nan
    data.loc[data.index[10:12], "region"] = None
    return data


@pytest.fixture(scope="module")
def series_frame() -> pd.DataFrame:
    """A monthly series with a trend, a seasonal cycle, and a leading driver.

    ``value`` is an AR(1) driven by the previous period's ``driver``, so the
    Granger test has something real to find and the ACF has structure to show.
    Fourteen years of monthly data: enough for STL's three cycles, for an ADF
    test to have lags, and for a forecast to have history behind it.
    """
    rng = np.random.default_rng(4242)
    n = 168
    t = np.arange(n, dtype=float)
    driver = np.sin(2 * np.pi * t / 12) * 8 + rng.normal(0, 1.0, n) + 0.05 * t
    value = np.empty(n)
    value[0] = driver[0]
    for step in range(1, n):
        value[step] = 0.6 * value[step - 1] + 0.4 * driver[step - 1] + rng.normal(0, 1.0)
    return pd.DataFrame(
        {
            "date": pd.date_range("2012-01-31", periods=n, freq="ME"),
            "value": value + 50,
            "driver": driver + 20,
        }
    )


@pytest.fixture(scope="module")
def hostile_frame() -> pd.DataFrame:
    """Column names and category values that are not safe to interpolate.

    Sixty monthly rows rather than an arbitrary count, so the Tier 5 operations
    can run on it too: a decomposition needs whole cycles and an ARIMA needs
    history, and a hostile column name has to survive both.
    """
    rng = np.random.default_rng(4242)
    n = 60
    return pd.DataFrame(
        {
            QUOTED: rng.choice(['say "hi"', "it's fine", "plain"], n),
            BACKSLASH: rng.choice(["C:\\Users\\a", "/tmp/b"], n),
            NEWLINE: rng.choice(["two\nlines", "one line"], n),
            UNICODE: rng.normal(10, 2, n),
            SPACED: rng.normal(5, 1, n),
            BUILTIN: rng.normal(100, 15, n),
            KEYWORD: rng.choice(["alpha", "beta"], n),
            DATED: pd.date_range("2019-01-31", periods=n, freq="ME"),
        }
    )


# ---------------------------------------------------------------------------
# Running a generated script
# ---------------------------------------------------------------------------


def run_python_export(script: str, data: pd.DataFrame) -> dict[str, Any]:
    """Execute a generated script against *data*, substituting only the load line."""
    load = python_load_statement("data.csv")
    assert load in script, f"the load line {load!r} is not a single substitutable statement"
    runnable = script.replace(load, "df = _INPUT_FRAME")
    namespace: dict[str, Any] = {"_INPUT_FRAME": data.copy()}
    exec(compile(runnable, "<export>", "exec"), namespace)  # noqa: S102
    return namespace


def run_r_export(script: str, data: pd.DataFrame) -> dict[str, Any]:
    """Execute a generated R script against *data*, reading back result_N as JSON."""
    assert RSCRIPT is not None
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        csv_path = root / "data.csv"
        data.to_csv(csv_path, index=False)
        body = script.replace(r_load_statement("data.csv"), r_load_statement(str(csv_path)))
        body += (
            "\n\n"
            'captured <- mget(ls(pattern = "^(result|stats)_[0-9]+$"), '
            "envir = environment())\n"
            'cat(jsonlite::toJSON(captured, dataframe = "columns", digits = NA, na = "null"), '
            'file = "%s")\n' % (root / "out.json")
        )
        script_path = root / "export.R"
        script_path.write_text(body, encoding="utf-8")
        completed = subprocess.run(
            [RSCRIPT, "--vanilla", str(script_path)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads((root / "out.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Comparing an export to the product's own result
# ---------------------------------------------------------------------------


def _cells(exported: pd.DataFrame) -> list[list[Any]]:
    """Apply the product's own display coercion, so like is compared with like."""
    return [
        [to_python(value) for value in row]
        for row in exported.head(MAX_RESULT_ROWS).itertuples(index=False, name=None)
    ]


def assert_same_value(got: Any, want: Any, where: str, tolerance: float = TOLERANCE) -> None:
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        assert isinstance(got, (int, float)), f"{where}: expected a number, got {got!r}"
        assert got == pytest.approx(want, rel=tolerance, abs=tolerance), where
    else:
        assert got == want, where


def assert_frame_matches(
    exported: pd.DataFrame,
    result: OperationResult,
    *,
    skip: tuple[str, ...] = (),
    tolerance: float = TOLERANCE,
) -> None:
    """The exported table must be the product's table, column for column."""
    expected_columns = [name for name in result.columns if name not in skip]
    got_columns = [str(name) for name in exported.columns]
    assert got_columns == expected_columns, "exported columns differ from the product's"

    keep = [result.columns.index(name) for name in expected_columns]
    got_rows = _cells(exported)
    want_rows = [[row[index] for index in keep] for row in result.rows]
    assert len(got_rows) == len(want_rows), "exported row count differs"
    for row_number, (got_row, want_row) in enumerate(zip(got_rows, want_rows, strict=True)):
        for name, got, want in zip(expected_columns, got_row, want_row, strict=True):
            assert_same_value(got, want, f"row {row_number}, column {name!r}", tolerance)


def dig(payload: dict[str, Any], path: str) -> Any:
    node: Any = payload
    for key in path.split("."):
        node = node[key]
    return node


# ---------------------------------------------------------------------------
# The cases: one per operation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One spec, and how to line its export up against the product's result."""

    name: str
    spec: dict[str, Any]
    # (key in the exported ``stats_N`` dict, dotted path into result.stats)
    stats_map: tuple[tuple[str, str], ...] = ()
    # Columns the export deliberately omits, with the reason stated in the report.
    skip_columns: tuple[str, ...] = ()
    r_contains: tuple[str, ...] = field(default=())
    # Which fixture the spec runs against: the descriptive frame, the frame the
    # models need, or the monthly series.
    frame: str = "frame"
    tolerance: float = TOLERANCE


def one(op: str, params: dict[str, Any], *, label: str = "Result") -> dict[str, Any]:
    return {"operations": [{"op": op, "label": label, "params": params}]}


CASES: tuple[Case, ...] = (
    Case(
        "describe",
        one("describe", {"columns": ["revenue", "cost"]}),
        r_contains=("quantile(",),
    ),
    Case(
        "describe_all_numeric",
        one("describe", {}),
        r_contains=("quantile(",),
    ),
    Case(
        "groupby_aggregate_sum",
        one("groupby_aggregate", {"group_by": ["region"], "column": "revenue", "agg": "sum"}),
        r_contains=("group_by(", "summarise("),
    ),
    Case(
        "groupby_aggregate_count",
        one(
            "groupby_aggregate",
            {"group_by": ["region", "segment"], "column": "revenue", "agg": "count"},
        ),
        r_contains=("group_by(",),
    ),
    Case(
        "groupby_aggregate_nunique",
        one("groupby_aggregate", {"group_by": ["region"], "column": "segment", "agg": "nunique"}),
        r_contains=("n_distinct(",),
    ),
    Case(
        "value_counts",
        one("value_counts", {"column": "region"}),
        r_contains=("count(",),
    ),
    Case(
        "value_counts_normalized",
        one("value_counts", {"column": "segment", "normalize": True, "top_n": 2}),
    ),
    Case(
        "crosstab",
        one("crosstab", {"row": "region", "column": "segment"}),
        stats_map=(("chi2", "chi2"), ("p_value", "p_value"), ("dof", "dof")),
        r_contains=("chisq.test(",),
    ),
    Case(
        "histogram",
        one("histogram", {"column": "revenue", "bins": 6}),
        r_contains=("cut(",),
    ),
    Case(
        "top_n",
        one("top_n", {"column": "region", "by": "revenue", "n": 5}),
        r_contains=("head(",),
    ),
    Case(
        "pivot",
        one(
            "pivot",
            {"index": ["region"], "columns": "segment", "values": "revenue", "agg": "mean"},
        ),
        r_contains=("pivot_wider(",),
    ),
    Case(
        "resample",
        one(
            "resample",
            {
                "date_column": "signup_date",
                "column": "revenue",
                "freq": "ME",
                "agg": "sum",
            },
        ),
        r_contains=("cut(",),
    ),
    Case(
        "correlation_matrix",
        one("correlation_matrix", {"columns": ["revenue", "cost", "before"]}),
        r_contains=("cor(", "cor.test("),
    ),
    Case(
        "correlation_matrix_spearman",
        one("correlation_matrix", {"columns": ["revenue", "cost"], "method": "spearman"}),
    ),
    Case(
        "scatter_with_fit",
        one("scatter_with_fit", {"x": "cost", "y": "revenue"}),
        stats_map=(
            ("slope", "slope"),
            ("intercept", "intercept"),
            ("r_squared", "r_squared"),
            ("p_value", "p_value"),
            ("std_err", "std_err"),
        ),
        r_contains=("lm(",),
    ),
    Case(
        "group_comparison",
        one("group_comparison", {"group_by": "segment", "column": "revenue"}),
        stats_map=(("statistic", "statistic"), ("p_value", "p_value")),
        r_contains=("t.test(",),
    ),
    Case(
        "group_comparison_anova",
        one("group_comparison", {"group_by": "region", "column": "revenue"}),
        stats_map=(("statistic", "statistic"), ("p_value", "p_value")),
    ),
    Case(
        "ttest_one_sample",
        one("ttest", {"kind": "one_sample", "column": "revenue", "mu": 1000}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("mean_difference", "mean_difference"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("t.test(",),
    ),
    Case(
        "ttest_independent",
        one("ttest", {"kind": "independent", "column": "revenue", "group_by": "segment"}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("mean_difference", "mean_difference"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
            ("hedges_g", "effect_size.hedges_g"),
        ),
        r_contains=("t.test(",),
    ),
    Case(
        "ttest_independent_pooled",
        one(
            "ttest",
            {
                "kind": "independent",
                "column": "revenue",
                "group_by": "segment",
                "equal_var": True,
                "alternative": "greater",
            },
        ),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
        ),
    ),
    Case(
        "ttest_paired",
        one("ttest", {"kind": "paired", "column": "after", "column2": "before"}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("mean_difference", "mean_difference"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("paired = TRUE",),
    ),
    Case(
        "anova",
        one("anova", {"group_by": "region", "column": "revenue"}),
        stats_map=(
            ("statistic", "statistic"),
            ("df_between", "df_between"),
            ("df_within", "df_within"),
            ("p_value", "p_value"),
            ("effect_size", "effect_size.value"),
            ("omega_squared", "effect_size.omega_squared"),
        ),
        r_contains=("aov(", "TukeyHSD("),
    ),
    Case(
        "kruskal",
        one("kruskal", {"group_by": "region", "column": "revenue"}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("kruskal.test(",),
    ),
    Case(
        "mannwhitney",
        one("mannwhitney", {"group_by": "segment", "column": "revenue"}),
        stats_map=(
            ("statistic", "statistic"),
            ("p_value", "p_value"),
            ("median_difference", "median_difference"),
            ("hodges_lehmann_shift", "hodges_lehmann_shift"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("wilcox.test(",),
    ),
    Case(
        "wilcoxon",
        one("wilcoxon", {"column": "after", "column2": "before"}),
        stats_map=(
            ("statistic", "statistic"),
            ("p_value", "p_value"),
            ("median_difference", "median_difference"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("wilcox.test(",),
    ),
    Case(
        "chi_square_independence",
        one("chi_square", {"kind": "independence", "row": "region", "column": "segment"}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("chisq.test(",),
    ),
    Case(
        "chi_square_2x2",
        one("chi_square", {"kind": "independence", "row": "segment", "column": "converted"}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("effect_size", "effect_size.value"),
            ("fisher_odds_ratio", "fisher_exact.odds_ratio"),
            ("fisher_p_value", "fisher_exact.p_value"),
        ),
        r_contains=("fisher.test(",),
    ),
    Case(
        "chi_square_goodness_of_fit",
        one("chi_square", {"kind": "goodness_of_fit", "column": "region"}),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("effect_size", "effect_size.value"),
        ),
    ),
    Case(
        "proportion_test_one_sample",
        one(
            "proportion_test",
            {"column": "converted", "success_value": "yes", "p0": 0.5},
        ),
        stats_map=(
            ("statistic", "statistic"),
            ("p_value", "p_value"),
            ("proportion", "proportion"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("pnorm(",),
    ),
    Case(
        "proportion_test_two_sample",
        one(
            "proportion_test",
            {"column": "converted", "success_value": "yes", "group_by": "segment"},
        ),
        stats_map=(
            ("statistic", "statistic"),
            ("p_value", "p_value"),
            ("difference", "difference"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
    ),
    Case(
        "normality_test",
        one("normality_test", {"column": "revenue"}),
        # The product's prose verdict is rendered from these numbers; the export
        # prints the numbers rather than re-deriving the product's wording.
        skip_columns=("verdict",),
        r_contains=("shapiro.test(",),
    ),
    Case(
        "normality_test_grouped",
        one("normality_test", {"column": "revenue", "group_by": "region"}),
        skip_columns=("verdict",),
    ),
    # -----------------------------------------------------------------------
    # Tier 4 — regression
    # -----------------------------------------------------------------------
    Case(
        "ols",
        one("ols", {"y": "revenue", "x": ["cost", "region"]}),
        stats_map=(
            ("n", "n"),
            ("n_excluded", "n_excluded"),
            ("r_squared", "r_squared"),
            ("adj_r_squared", "adj_r_squared"),
            ("f_statistic", "f_statistic"),
            ("f_p_value", "f_p_value"),
            ("rmse", "rmse"),
            ("residual_std_error", "residual_std_error"),
            ("aic", "aic"),
            ("bic", "bic"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("lm(y_ ~ ., data =", "sandwich::vcovHC", "lmtest::coefci"),
        frame="models",
    ),
    Case(
        "ols_classical_errors",
        one("ols", {"y": "revenue", "x": ["cost"], "robust": "none"}),
        stats_map=(("r_squared", "r_squared"), ("f_statistic", "f_statistic")),
        r_contains=("confint(fit_1",),
        frame="models",
    ),
    Case(
        "logit",
        one("logit", {"y": "converted", "success_value": "yes", "x": ["revenue", "segment"]}),
        stats_map=(
            ("successes", "successes"),
            ("base_rate", "base_rate"),
            ("log_likelihood", "log_likelihood"),
            ("null_log_likelihood", "null_log_likelihood"),
            ("pseudo_r_squared", "pseudo_r_squared"),
            ("llr_statistic", "llr_statistic"),
            ("llr_p_value", "llr_p_value"),
            ("aic", "aic"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        # confint.default is the Wald interval statsmodels reports; plain
        # confint on a glm is a profile-likelihood interval and a different
        # number, which is why the export must name the default form.
        r_contains=("family = binomial()", "confint.default(fit_1"),
        frame="models",
    ),
    Case(
        "count_model_poisson",
        one("count_model", {"y": "orders", "x": ["cost", "region"], "exposure": "exposure"}),
        stats_map=(
            ("mean_outcome", "mean_outcome"),
            ("variance_outcome", "variance_outcome"),
            ("pseudo_r_squared", "pseudo_r_squared"),
            ("aic", "aic"),
            ("bic", "bic"),
            ("pearson_chi2", "dispersion.pearson_chi2"),
            ("dispersion_ratio", "dispersion.ratio"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("family = poisson()", "offset = log("),
        frame="models",
    ),
    Case(
        "count_model_negative_binomial",
        one("count_model", {"y": "orders", "x": ["cost"], "family": "negative_binomial"}),
        stats_map=(
            ("aic", "aic"),
            ("pearson_chi2", "dispersion.pearson_chi2"),
            ("dispersion_ratio", "dispersion.ratio"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("MASS::glm.nb",),
        frame="models",
        tolerance=ITERATIVE_TOLERANCE,
    ),
    Case(
        "quantile_regression",
        one("quantile_regression", {"y": "revenue", "x": ["cost", "region"], "tau": 0.25}),
        stats_map=(
            ("tau", "tau"),
            ("pseudo_r_squared", "pseudo_r_squared"),
            ("share_below_fit", "share_below_fit"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("quantreg::rq", 'se = "nid"'),
        frame="models",
        tolerance=ITERATIVE_TOLERANCE,
    ),
    # -----------------------------------------------------------------------
    # Tier 5 — time series
    # -----------------------------------------------------------------------
    Case(
        "decompose",
        one("decompose", {"date": "date", "value": "value", "freq": "ME"}),
        stats_map=(
            ("method", "method"),
            ("seasonal_period", "seasonal_period"),
            ("trend_strength", "trend_strength"),
            ("seasonal_strength", "seasonal_strength"),
            ("trend_slope_per_period", "trend_slope_per_period"),
            ("seasonal_amplitude", "seasonal_amplitude"),
            ("seasonal_peak_to_trough", "seasonal_peak_to_trough"),
            ("residual_sd", "residual_sd"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("stl(", "s.degree = 0"),
        frame="series",
    ),
    Case(
        "stationarity_test",
        one("stationarity_test", {"date": "date", "value": "value", "freq": "ME"}),
        stats_map=(
            ("adf_statistic", "adf.statistic"),
            ("adf_p_value", "adf.p_value"),
            ("kpss_statistic", "kpss.statistic"),
            ("kpss_p_value", "kpss.p_value"),
            ("differences_suggested", "differences_suggested"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("urca::ur.df", "tseries::kpss.test"),
        frame="series",
    ),
    Case(
        "autocorrelation",
        one("autocorrelation", {"date": "date", "value": "value", "freq": "ME", "lags": 14}),
        stats_map=(
            ("lags", "lags"),
            ("ljung_box_statistic", "ljung_box.statistic"),
            ("ljung_box_dof", "ljung_box.dof"),
            ("ljung_box_p_value", "ljung_box.p_value"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("bartlett_band(", 'type = "Ljung-Box"'),
        frame="series",
    ),
    Case(
        "autocorrelation_default_lags",
        one("autocorrelation", {"date": "date", "value": "value", "freq": "ME"}),
        stats_map=(("lags", "lags"), ("effect_size", "effect_size.value")),
        frame="series",
    ),
    Case(
        "arima",
        one("arima", {"date": "date", "value": "value", "freq": "ME", "p": 1, "d": 0, "q": 1}),
        stats_map=(
            ("aic", "aic"),
            ("bic", "bic"),
            ("hqic", "hqic"),
            ("log_likelihood", "log_likelihood"),
            ("sigma2", "sigma2"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("arima(", 'method = "ML"'),
        frame="series",
        tolerance=ITERATIVE_TOLERANCE,
    ),
    Case(
        "arima_with_forecast",
        one(
            "arima",
            {
                "date": "date",
                "value": "value",
                "freq": "ME",
                "p": 1,
                "d": 0,
                "q": 0,
                "forecast_periods": 6,
            },
        ),
        stats_map=(("aic", "aic"), ("effect_size", "effect_size.value")),
        r_contains=("predict(fit_1, n.ahead = 6)", 'kind = "forecast"'),
        frame="series",
        tolerance=ITERATIVE_TOLERANCE,
    ),
    Case(
        "granger_causality",
        one("granger_causality", {"date": "date", "value": "value", "cause": "driver"}),
        stats_map=(
            ("max_lag", "max_lag"),
            ("differences_applied", "differences_applied"),
            ("best_lag", "best_lag"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("lmtest::grangertest", 'method = "BH"'),
        frame="series",
    ),
    # -----------------------------------------------------------------------
    # Tier 6 — survey estimation
    # -----------------------------------------------------------------------
    Case(
        "weighted_mean",
        one("weighted_mean", {"column": "revenue", "weights": "weight"}),
        stats_map=(
            ("n", "n"),
            ("weighted_mean", "weighted_mean"),
            ("standard_error", "standard_error"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("relative_standard_error", "relative_standard_error"),
            ("sum_of_weights", "sum_of_weights"),
            ("degrees_of_freedom", "degrees_of_freedom"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("svydesign(", "svymean(~y_", "degf(design_1)"),
        frame="models",
    ),
    Case(
        "weighted_mean_grouped_stratified_clustered",
        one(
            "weighted_mean",
            {
                "column": "revenue",
                "weights": "weight",
                "group_by": ["segment"],
                "strata": "stratum",
                "cluster": "psu",
            },
        ),
        stats_map=(
            ("n", "n"),
            ("degrees_of_freedom", "degrees_of_freedom"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("svyby(~y_, ~g_", "strata = ~s_", "ids = ~psu_"),
        frame="models",
    ),
    Case(
        "weighted_total_with_fpc",
        one("weighted_total", {"column": "revenue", "weights": "weight", "fpc": 0.1}),
        stats_map=(
            ("weighted_total", "weighted_total"),
            ("standard_error", "standard_error"),
            ("ci95_low", "confidence_interval.low"),
            ("ci95_high", "confidence_interval.high"),
            ("estimated_population", "estimated_population"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("svytotal(~y_", "fpc = ~fpc_"),
        frame="models",
    ),
    Case(
        "design_effect",
        one("design_effect", {"column": "revenue", "weights": "weight", "group_by": ["region"]}),
        stats_map=(
            ("design_effect_kish", "design_effect_kish"),
            ("design_effect_design_based", "design_effect_design_based"),
            ("effective_sample_size", "effective_sample_size"),
            ("effective_sample_size_design_based", "effective_sample_size_design_based"),
            ("weight_cv", "weight_cv"),
            ("weight_min", "weight_min"),
            ("weight_max", "weight_max"),
            ("weighted_mean", "weighted_mean"),
            ("unweighted_mean", "unweighted_mean"),
            ("effect_size", "effect_size.value"),
        ),
        r_contains=("deff = TRUE", "deff(estimate)"),
        frame="models",
    ),
    Case(
        "weighted_crosstab",
        one(
            "weighted_crosstab",
            {"row": "region", "column": "segment", "weights": "weight", "strata": "stratum"},
        ),
        stats_map=(
            ("statistic", "statistic"),
            ("dof", "dof"),
            ("p_value", "p_value"),
            ("correction_factor", "correction_factor"),
            ("uncorrected_statistic", "uncorrected_statistic"),
            ("naive_weighted_statistic", "naive_weighted_statistic"),
            ("naive_weighted_p_value", "naive_weighted_p_value"),
            ("effective_sample_size", "effective_sample_size"),
            ("estimated_population", "estimated_population"),
            ("effect_size", "effect_size.value"),
        ),
        # svychisq(statistic = "Chisq") is the first-order Rao-Scott correction
        # the product computes; the package default is the second-order F.
        r_contains=("svytable(~row_ + col_", 'statistic = "Chisq"'),
        frame="models",
    ),
    Case(
        "subpopulation_estimate",
        one(
            "subpopulation_estimate",
            {
                "column": "revenue",
                "weights": "weight",
                "subpopulation": "region",
                "subpopulation_value": "North",
            },
        ),
        stats_map=(
            ("n", "n"),
            ("n_out_of_domain", "n_out_of_domain"),
            ("weighted_mean", "weighted_mean"),
            ("unweighted_mean", "unweighted_mean"),
            ("sum_of_weights", "sum_of_weights"),
            ("standard_error", "domain_estimation.standard_error"),
            ("ci95_low", "domain_estimation.confidence_interval.low"),
            ("ci95_high", "domain_estimation.confidence_interval.high"),
            ("degrees_of_freedom", "domain_estimation.degrees_of_freedom"),
            ("naive_standard_error", "naive_filter_then_analyze.standard_error"),
            ("naive_degrees_of_freedom", "naive_filter_then_analyze.degrees_of_freedom"),
            ("standard_error_ratio", "standard_error_ratio"),
            ("effect_size", "effect_size.value"),
        ),
        # subset() on a survey design is domain estimation; rebuilding the
        # design from the filtered rows is the naive comparison beside it.
        r_contains=("subset(design_1, dom_)", "naive_design_1 <- svydesign("),
        frame="models",
    ),
    Case(
        "filtered_multi_operation",
        {
            "rationale": "Revenue by region among Enterprise accounts",
            "filter": {"column": "segment", "operator": "==", "value": "Enterprise"},
            "operations": [
                {
                    "op": "groupby_aggregate",
                    "label": "Revenue by region",
                    "params": {"group_by": ["region"], "column": "revenue", "agg": "mean"},
                },
                {
                    "op": "value_counts",
                    "label": "Rows per region",
                    "params": {"column": "region"},
                },
            ],
        },
    ),
)

FILTER_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("equals", {"column": "region", "operator": "==", "value": "West"}),
    ("not_equals", {"column": "region", "operator": "!=", "value": "West"}),
    ("greater", {"column": "revenue", "operator": ">", "value": 1000}),
    ("greater_equal", {"column": "revenue", "operator": ">=", "value": 1000}),
    ("less", {"column": "revenue", "operator": "<", "value": 1000}),
    ("less_equal", {"column": "revenue", "operator": "<=", "value": 1000}),
    ("contains", {"column": "region", "operator": "contains", "value": "es"}),
    ("not_contains", {"column": "region", "operator": "not_contains", "value": "es"}),
    ("is_null", {"column": "region", "operator": "is_null"}),
    ("is_not_null", {"column": "region", "operator": "is_not_null"}),
)


# ---------------------------------------------------------------------------
# The central test: the export reproduces the product
# ---------------------------------------------------------------------------


class TestPythonExportReproducesTheProduct:
    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
    def test_tables_and_statistics_agree(
        self,
        case: Case,
        frame: pd.DataFrame,
        model_frame: pd.DataFrame,
        series_frame: pd.DataFrame,
    ):
        data = {"frame": frame, "models": model_frame, "series": series_frame}[case.frame]
        results = execute_spec(data, case.spec)
        assert len(results) == len(case.spec["operations"]), "an operation failed to execute"

        script = export_code(case.spec, language="python")
        namespace = run_python_export(script, data)

        for position, result in enumerate(results, start=1):
            assert_frame_matches(
                namespace[f"result_{position}"],
                result,
                skip=case.skip_columns,
                tolerance=case.tolerance,
            )

        for exported_key, path in case.stats_map:
            assert_same_value(
                namespace["stats_1"][exported_key],
                dig(results[0].stats, path),
                f"{case.name}: stats_1[{exported_key!r}] vs {path}",
                case.tolerance,
            )

    @pytest.mark.parametrize("name,spec_filter", FILTER_CASES, ids=lambda value: str(value)[:24])
    def test_every_filter_operator_selects_the_same_rows(
        self, name: str, spec_filter: dict[str, Any], frame: pd.DataFrame
    ):
        spec = {
            "filter": spec_filter,
            "operations": [
                {"op": "value_counts", "label": "Rows", "params": {"column": "segment"}}
            ],
        }
        results = execute_spec(frame, spec)
        namespace = run_python_export(export_code(spec, language="python"), frame)
        assert_frame_matches(namespace["result_1"], results[0])
        # The filtered frame itself must match, not just the aggregate over it.
        assert len(namespace["d"]) == results[0].n + results[0].n_excluded


class TestHostileNames:
    """Column names and values that are not safe to interpolate into source."""

    def test_python_round_trips_every_adversarial_name(self, hostile_frame: pd.DataFrame):
        spec = {
            "filter": {"column": BACKSLASH, "operator": "!=", "value": "C:\\Users\\a"},
            "operations": [
                {
                    "op": "groupby_aggregate",
                    "label": 'Mean of "sum" by it\'s a "test"',
                    "params": {"group_by": [QUOTED], "column": BUILTIN, "agg": "mean"},
                },
                {"op": "value_counts", "label": "Lines", "params": {"column": NEWLINE}},
                {
                    "op": "ttest",
                    "label": "café by class",
                    "params": {"kind": "independent", "column": UNICODE, "group_by": KEYWORD},
                },
                {
                    "op": "scatter_with_fit",
                    "label": "spaces vs sum",
                    "params": {"x": SPACED, "y": BUILTIN},
                },
            ],
        }
        results = execute_spec(hostile_frame, spec)
        assert len(results) == 4

        script = export_code(spec, language="python")
        namespace = run_python_export(script, hostile_frame)
        for position, result in enumerate(results, start=1):
            assert_frame_matches(namespace[f"result_{position}"], result)

    def test_python_round_trips_the_modelled_tiers(self, hostile_frame: pd.DataFrame):
        """Regression and survey blocks reach columns through literals too.

        These blocks put a column name in more places than Tier 1 does — a
        design matrix, a dummy-coded term label, a survey formula — so each is
        a separate chance to interpolate a name raw.
        """
        spec = {
            "operations": [
                {
                    "op": "ols",
                    "label": 'café on "spaces" and class',
                    "params": {"y": UNICODE, "x": [SPACED, KEYWORD]},
                },
                {
                    "op": "logit",
                    "label": "class from café",
                    "params": {"y": KEYWORD, "success_value": "alpha", "x": [UNICODE]},
                },
                {
                    "op": "count_model",
                    "label": "sum on spaces",
                    "params": {"y": BUILTIN, "x": [SPACED]},
                },
                {
                    "op": "quantile_regression",
                    "label": "median café",
                    "params": {"y": UNICODE, "x": [SPACED], "tau": 0.4},
                },
                {
                    "op": "weighted_mean",
                    "label": "café weighted by sum",
                    "params": {"column": UNICODE, "weights": BUILTIN, "group_by": [QUOTED]},
                },
                {
                    "op": "weighted_total",
                    "label": "total café",
                    "params": {"column": UNICODE, "weights": BUILTIN},
                },
                {
                    "op": "design_effect",
                    "label": "what the weights cost",
                    "params": {"column": SPACED, "weights": BUILTIN, "group_by": [KEYWORD]},
                },
                {
                    "op": "weighted_crosstab",
                    "label": "quoted by class",
                    "params": {"row": QUOTED, "column": KEYWORD, "weights": BUILTIN},
                },
                {
                    "op": "subpopulation_estimate",
                    "label": "café among alpha",
                    "params": {
                        "column": UNICODE,
                        "weights": BUILTIN,
                        "subpopulation": KEYWORD,
                        "subpopulation_value": "alpha",
                    },
                },
            ]
        }
        results = execute_spec(hostile_frame, spec)
        assert len(results) == len(spec["operations"]), "an operation failed to execute"

        namespace = run_python_export(export_code(spec, language="python"), hostile_frame)
        for position, result in enumerate(results, start=1):
            assert_frame_matches(namespace[f"result_{position}"], result)

    def test_python_round_trips_the_time_series_tier(self, hostile_frame: pd.DataFrame):
        """A hostile date column has to survive resampling as well as quoting."""
        spec = {
            "operations": [
                {
                    "op": "decompose",
                    "label": "café over time",
                    "params": {"date": DATED, "value": UNICODE, "freq": "ME"},
                },
                {
                    "op": "stationarity_test",
                    "label": "is café stationary",
                    "params": {"date": DATED, "value": UNICODE, "freq": "ME"},
                },
                {
                    "op": "autocorrelation",
                    "label": "spaces against itself",
                    "params": {"date": DATED, "value": SPACED, "freq": "ME"},
                },
                {
                    "op": "arima",
                    "label": "café, fitted",
                    "params": {
                        "date": DATED,
                        "value": UNICODE,
                        "freq": "ME",
                        "p": 1,
                        "d": 0,
                        "q": 0,
                    },
                },
                {
                    "op": "granger_causality",
                    "label": "does spaces lead café",
                    "params": {"date": DATED, "value": UNICODE, "cause": SPACED, "freq": "ME"},
                },
            ]
        }
        results = execute_spec(hostile_frame, spec)
        assert len(results) == len(spec["operations"]), "an operation failed to execute"

        namespace = run_python_export(export_code(spec, language="python"), hostile_frame)
        for position, result in enumerate(results, start=1):
            assert_frame_matches(namespace[f"result_{position}"], result)

    def test_python_literals_escape_correctly(self):
        assert py_literal(QUOTED) == repr(QUOTED)
        assert eval(py_literal(QUOTED)) == QUOTED  # noqa: S307
        for name in ADVERSARIAL_COLUMNS:
            assert eval(py_literal(name)) == name  # noqa: S307
        assert eval(py_literal([QUOTED, NEWLINE])) == [QUOTED, NEWLINE]  # noqa: S307
        assert py_literal(True) == "True"
        assert py_literal(None) == "None"
        assert py_literal(float("nan")) == "float('nan')"
        assert eval(py_literal(np.int64(7))) == 7  # noqa: S307
        assert eval(py_literal(np.float64(1.5))) == 1.5  # noqa: S307

    def test_r_literals_escape_correctly(self):
        assert r_literal(QUOTED) == '"it\'s a \\"test\\""'
        assert r_literal(BACKSLASH) == '"back\\\\slash\\\\path"'
        assert r_literal(NEWLINE) == '"line\\nbreak"'
        assert r_literal(UNICODE) == f'"{UNICODE}"'
        assert r_literal(True) == "TRUE"
        assert r_literal(None) == "NULL"
        assert r_literal([QUOTED, SPACED]) == f"c({r_literal(QUOTED)}, {r_literal(SPACED)})"
        for name in ADVERSARIAL_COLUMNS:
            assert decode_r_string(r_literal(name)) == name

    def test_r_export_quotes_every_adversarial_name(self, hostile_frame: pd.DataFrame):
        spec = {
            "filter": {"column": BACKSLASH, "operator": "contains", "value": "tmp"},
            "operations": [
                {
                    "op": "groupby_aggregate",
                    "label": "Mean by " + QUOTED,
                    "params": {"group_by": [QUOTED], "column": BUILTIN, "agg": "mean"},
                },
                {
                    "op": "ttest",
                    "label": "café by class",
                    "params": {"kind": "independent", "column": UNICODE, "group_by": KEYWORD},
                },
            ],
        }
        script = export_code(spec, language="r")
        for name in (QUOTED, BACKSLASH, BUILTIN, UNICODE, KEYWORD):
            assert r_literal(name) in script
        # A raw newline may never leak out of a string literal or a comment.
        assert_r_brackets_balance(script)
        assert "line\nbreak" not in script.replace(r_literal(NEWLINE), "")

    def test_r_modelled_tiers_never_put_a_name_in_a_formula(self):
        """The models are formula-driven, which is where R is easiest to break.

        ``lm``, ``glm``, ``rq`` and every ``svy*`` call need syntactic
        identifiers, and an uploaded column name is not one. The export must
        therefore copy the columns under generated names first, so the emitted
        formulas mention only ``y_``, ``t1_``, ``w_`` and friends — never a
        column name, quoted or otherwise.
        """
        spec = {
            "operations": [
                {
                    "op": "ols",
                    "label": "café",
                    "params": {"y": UNICODE, "x": [SPACED, KEYWORD]},
                },
                {
                    "op": "weighted_mean",
                    "label": "weighted café",
                    "params": {"column": UNICODE, "weights": BUILTIN, "group_by": [QUOTED]},
                },
                {
                    "op": "granger_causality",
                    "label": "lead",
                    "params": {"date": DATED, "value": UNICODE, "cause": SPACED, "freq": "ME"},
                },
            ]
        }
        script = export_code(spec, language="r")
        assert_r_brackets_balance(script)
        for name in (UNICODE, SPACED, KEYWORD, QUOTED, BUILTIN, DATED):
            assert r_literal(name) in script, f"{name!r} never reached the script as a literal"

        # Every formula in the emitted script, and what may appear in one.
        generated = {"y_", "x_", "w_", "s_", "psu_", "g_", "row_", "col_", "dom_", "fpc_", "."}
        for line in script.splitlines():
            for fragment in re.findall(r"~\s*([A-Za-z0-9_. +]+)", line):
                for token in re.split(r"[+\s]+", fragment.strip()):
                    if token:
                        assert token in generated, f"{token!r} in a formula: {line!r}"

    def test_r_names_every_package_it_calls(self):
        """A pkg::fn() the install line does not mention is a script that fails late."""
        base_r = {"stats", "utils", "base", "graphics", "grDevices", "methods"}
        for case in CASES:
            script = export_code(case.spec, language="r")
            used = set(re.findall(r"\b([A-Za-z][A-Za-z0-9.]*)::", script)) - base_r
            attached = set(re.findall(r"\blibrary\(([A-Za-z][A-Za-z0-9.]*)\)", script))
            declared = set(
                re.findall(
                    r'"([A-Za-z][A-Za-z0-9.]*)"',
                    "".join(line for line in script.splitlines() if "install.packages" in line),
                )
            )
            missing = sorted((used | attached) - declared - {"dplyr", "tidyr"})
            assert missing == [], f"{case.name}: {missing} used but never named for installation"


# ---------------------------------------------------------------------------
# Coverage, extension point, and the unknown-operation path
# ---------------------------------------------------------------------------


class TestCoverage:
    """Every registered operation is exported, in both languages, and executed here.

    This is the class that keeps the feature honest. An export that silently
    omits an operation reads as a complete reproduction and is not one, so a
    tier added without an emitter has to fail a test rather than quietly emit a
    "no code equivalent" comment; and an emitter that is never run against the
    pipeline proves nothing, so every one of them appears in ``CASES``.
    """

    @pytest.mark.parametrize("language", ["python", "r"])
    def test_every_registered_operation_has_an_emitter(self, language: str):
        missing = sorted(frozenset(OPERATIONS) - supported_operations(language))
        assert missing == [], (
            f"{language}: no emitter for {missing}. Add one, or the export will "
            f"claim to reproduce an analysis it silently skipped."
        )

    def test_no_emitter_is_registered_for_an_operation_that_does_not_exist(self):
        """A stale emitter would export a spec the validator can never produce."""
        for language in ("python", "r"):
            unknown = sorted(supported_operations(language) - frozenset(OPERATIONS))
            assert unknown == [], f"{language}: emitter for unregistered {unknown}"

    def test_every_exported_operation_is_run_by_the_exec_and_compare_test(self):
        exercised = {operation["op"] for case in CASES for operation in case.spec["operations"]}
        assert sorted(exercised) == sorted(EXPORTED_OPS)

    def test_defaults_match_the_executor(self):
        from app.services import analysis_executor

        assert DEFAULT_TOP_N == analysis_executor.DEFAULT_TOP_N
        assert DEFAULT_VALUE_COUNTS == analysis_executor.DEFAULT_VALUE_COUNTS
        assert DEFAULT_BINS == analysis_executor.DEFAULT_BINS

    def test_model_constants_match_the_tier_modules(self):
        """A mirrored constant that drifts is a different number, silently."""
        from app.services import (
            analysis_codegen_python_models as models,
        )
        from app.services import (
            analysis_regression,
            analysis_regression_core,
            analysis_stats,
            analysis_timeseries,
            analysis_timeseries_prep,
        )

        assert models.INTERCEPT == analysis_regression_core.INTERCEPT
        assert models.P_VALUE_FLOOR == analysis_regression_core.P_VALUE_FLOOR
        assert models.LOGISTIC_TO_COHEN_D == analysis_regression.LOGISTIC_TO_COHEN_D
        assert models.QUANTREG_MAX_ITER == analysis_regression.QUANTREG_MAX_ITER
        assert models.DEFAULT_TAU == analysis_regression.DEFAULT_TAU
        assert models.MACKINNON_P_FLOOR == analysis_timeseries.MACKINNON_P_FLOOR
        assert models.STL_MIN_CYCLES == analysis_timeseries.STL_MIN_CYCLES
        assert models.STL_SEASONAL_CYCLES == analysis_timeseries.STL_SEASONAL_CYCLES
        assert models.MAX_LAG_FRACTION == analysis_timeseries.MAX_LAG_FRACTION
        assert models.MAX_LAGS == analysis_timeseries.MAX_LAGS
        assert models.MAX_DIFFERENCES == analysis_timeseries.MAX_DIFFERENCES
        assert models.MIN_RESIDUAL_PERIODS == analysis_timeseries.MIN_RESIDUAL_PERIODS
        assert models.FORECAST_CONTEXT_MULTIPLE == analysis_timeseries.FORECAST_CONTEXT_MULTIPLE
        assert models.MAX_FORECAST_CONTEXT == analysis_timeseries.MAX_FORECAST_CONTEXT
        assert models.SEASONAL_PERIODS == analysis_timeseries_prep.SEASONAL_PERIODS
        assert models.COEFFICIENT_P_FLOOR == analysis_stats.ALPHA / 1e8
        assert models.LJUNG_BOX_P_FLOOR == analysis_stats.ALPHA / 1e6
        assert models.ODDS_RATIO == (
            analysis_regression_core.ODDS_RATIO.value,
            analysis_regression_core.ODDS_RATIO.low,
            analysis_regression_core.ODDS_RATIO.high,
        )
        assert models.RATE_RATIO == (
            analysis_regression_core.RATE_RATIO.value,
            analysis_regression_core.RATE_RATIO.low,
            analysis_regression_core.RATE_RATIO.high,
        )


class TestUnknownOperation:
    """An export that quietly drops an operation is worse than one admitting the gap."""

    UNKNOWN = {
        "operations": [
            {"op": "value_counts", "label": "Regions", "params": {"column": "region"}},
            {
                "op": "diff_in_diff",
                "label": "Effect of the launch",
                "params": {"outcome": "revenue", "treated": "segment"},
            },
        ]
    }

    @pytest.mark.parametrize("language", ["python", "r"])
    def test_unknown_operation_is_marked_not_dropped(self, language: str):
        script = export_code(self.UNKNOWN, language=language)
        assert NO_EQUIVALENT_MARKER in script
        assert "diff_in_diff" in script
        assert unsupported_operations(self.UNKNOWN, language=language) == ["diff_in_diff"]

    def test_unknown_operation_leaves_the_rest_runnable(self, frame: pd.DataFrame):
        script = export_code(self.UNKNOWN, language="python")
        namespace = run_python_export(script, frame)
        assert "result_1" in namespace
        assert "result_2" not in namespace

    def test_registering_an_emitter_extends_the_export(self):
        from app.services.analysis_codegen_python import PYTHON_EMITTERS
        from app.services.analysis_codegen_r import R_EMITTERS

        def emit_python(params: dict[str, Any], label: str, index: int) -> list[str]:
            return [f"result_{index} = {py_literal(params['column'])}"]

        def emit_r(params: dict[str, Any], label: str, index: int) -> list[str]:
            return [f"result_{index} <- {r_literal(params['column'])}"]

        PYTHON_EMITTERS["fake_tier_4_op"] = emit_python
        R_EMITTERS["fake_tier_4_op"] = emit_r
        try:
            spec = one("fake_tier_4_op", {"column": QUOTED})
            assert unsupported_operations(spec, language="python") == []
            assert py_literal(QUOTED) in export_code(spec, language="python")
            assert r_literal(QUOTED) in export_code(spec, language="r")
        finally:
            del PYTHON_EMITTERS["fake_tier_4_op"]
            del R_EMITTERS["fake_tier_4_op"]


class TestScriptShape:
    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
    def test_python_script_compiles(self, case: Case):
        compile(export_code(case.spec, language="python"), "<export>", "exec")

    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
    def test_r_script_is_structurally_sound(self, case: Case):
        script = export_code(case.spec, language="r", source="my file.csv")
        assert_r_brackets_balance(script)
        assert r_load_statement("my file.csv") in script
        for fragment in case.r_contains:
            assert fragment in script, f"{case.name}: expected {fragment!r} in the R export"

    def test_headers_state_the_question_and_the_environment(self):
        from app.services.analysis_provenance import environment

        versions = environment()
        spec = one("value_counts", {"column": "region"})
        for language in ("python", "r"):
            script = export_code(spec, language=language, question="Which region converts best?")
            assert "Which region converts best?" in script
            assert versions["pandas"] in script or versions["python"] in script
            assert "match" in script.lower()

    def test_unknown_language_is_rejected(self):
        with pytest.raises(ValueError, match="julia"):
            export_code(one("value_counts", {"column": "region"}), language="julia")

    def test_refusal_spec_produces_no_operations(self):
        script = export_code({"refusal": "cannot be answered"}, language="python")
        assert "result_1" not in script


@requires_r
class TestRExportRunsAndAgrees:
    """Only runs where Rscript is installed; structural checks cover it otherwise."""

    @pytest.mark.parametrize(
        "case",
        [case for case in CASES if case.name in {"groupby_aggregate_sum", "ttest_independent"}],
        ids=lambda case: case.name,
    )
    def test_r_reproduces_the_headline_numbers(self, case: Case, frame: pd.DataFrame):
        results = execute_spec(frame, case.spec)
        captured = run_r_export(export_code(case.spec, language="r"), frame)
        assert "result_1" in captured
        for exported_key, path in case.stats_map:
            got = captured["stats_1"][exported_key]
            got = got[0] if isinstance(got, list) else got
            assert_same_value(got, dig(results[0].stats, path), exported_key)


# ---------------------------------------------------------------------------
# R helpers used by the structural checks
# ---------------------------------------------------------------------------

_R_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'"}


def decode_r_string(literal: str) -> str:
    """Inverse of :func:`r_literal` for strings, so escaping is proved not assumed."""
    assert literal.startswith('"') and literal.endswith('"'), literal
    body, out, index = literal[1:-1], [], 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        marker = body[index + 1]
        if marker == "u":
            assert body[index + 2] == "{"
            end = body.index("}", index)
            out.append(chr(int(body[index + 3 : end], 16)))
            index = end + 1
            continue
        out.append(_R_ESCAPES[marker])
        index += 2
    return "".join(out)


def strip_r_strings_and_comments(script: str) -> str:
    """Remove string literals and comments so brackets can be counted honestly."""
    out: list[str] = []
    index, length, quote = 0, len(script), ""
    while index < length:
        char = script[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
            index += 1
            continue
        if char == "#":
            while index < length and script[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    assert quote == "", "an R string literal was never closed"
    return "".join(out)


def assert_r_brackets_balance(script: str) -> None:
    code = strip_r_strings_and_comments(script)
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for char in code:
        if char in "([{":
            stack.append(char)
        elif char in pairs:
            assert stack and stack.pop() == pairs[char], "unbalanced brackets in the R export"
    assert not stack, "unclosed brackets in the R export"
