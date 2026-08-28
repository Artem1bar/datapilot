"""Tier 4 regression — coefficients, robust errors, diagnostics, and refusals.

No expected value below is read back out of statsmodels. The linear fixture is
solved again with numpy's least squares inside the test; the logistic fixture is
a 2x2 table whose maximum-likelihood odds ratio, standard error, log-likelihood
and interval all have closed forms; the count fixture is saturated, so its
fitted means are group means and its Pearson chi-square is arithmetic that fits
on one line. An implementation that merely agreed with itself would fail every
one of them.

The refusal tests matter as much as the estimates. A regression that runs on
data it cannot support does not fail loudly — it returns a full coefficient
table with standard errors that are artifacts of rounding, which is exactly the
kind of plausible-looking number this pipeline exists to prevent.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.services.analysis_executor import ExecutionError, execute_spec
from app.services.analysis_regression import (
    REGRESSION_OPERATION_DEFS,
    REGRESSION_OPERATIONS,
)
from app.services.analysis_spec import ColumnRoles, validate_spec

# The two-sided normal quantile behind a 95% interval, written out so the
# expected interval bounds below do not depend on scipy either.
Z_95 = 1.959963984540054

INTERCEPT = "(Intercept)"


def _run(df: pd.DataFrame, op: str, params: dict[str, Any], label: str = "R") -> Any:
    return execute_spec(df, {"operations": [{"op": op, "label": label, "params": params}]})[0]


def _terms(result: Any) -> dict[str, dict[str, Any]]:
    """The coefficient table, keyed by term."""
    return {row[0]: dict(zip(result.columns, row, strict=True)) for row in result.rows}


def _assumption(result: Any, needle: str) -> dict[str, Any]:
    for check in result.stats.get("assumptions", []):
        if needle.lower() in check["name"].lower():
            return check
    raise AssertionError(
        f"no assumption matching {needle!r}; have "
        f"{[c['name'] for c in result.stats.get('assumptions', [])]}"
    )


def _collect_p_values(node: Any, key: str = "") -> list[float]:
    """Every p-value anywhere in a nested payload, however deeply buried."""
    if isinstance(node, dict):
        found: list[float] = []
        for name, value in node.items():
            found += _collect_p_values(value, name)
        return found
    if isinstance(node, list):
        return [p for item in node for p in _collect_p_values(item, key)]
    if "p_value" in key and isinstance(node, (int, float)) and not isinstance(node, bool):
        return [float(node)]
    return []


def _validate(df: pd.DataFrame, op: str, params: dict[str, Any]) -> list[str]:
    return validate_spec(
        {"operations": [{"op": op, "label": "R", "params": params}]},
        ColumnRoles.from_dataframe(df),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

N_LINEAR = 60


@pytest.fixture
def linear() -> pd.DataFrame:
    """y = 3 + 2*x1 - 1.5*x2 + a deterministic wobble.

    Nothing here is drawn at random, so every fitted number is identical on
    every machine, and the wobble is large enough that the fit is not numerically
    perfect — a perfect fit is a refusal, tested separately.
    """
    index = np.arange(N_LINEAR, dtype=float)
    x1 = index / 10.0
    x2 = np.sin(index)
    wobble = 0.4 * np.cos(3.0 * index)
    return pd.DataFrame(
        {
            "x1": x1,
            "x2": x2,
            "y": 3.0 + 2.0 * x1 - 1.5 * x2 + wobble,
            "region": ["East", "North", "West"] * (N_LINEAR // 3),
        }
    )


def _least_squares(df: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Solve the same normal equations with numpy — the independent ground truth."""
    design = np.column_stack([np.ones(len(df))] + [df[c].to_numpy(dtype=float) for c in columns])
    y = df["y"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    return beta, y - design @ beta


@pytest.fixture
def heteroskedastic() -> pd.DataFrame:
    """Residual spread grows with x, so robust and classical errors must differ.

    Monotone in x rather than in |x|: Breusch-Pagan regresses the squared
    residuals on the regressors themselves, so a spread that is symmetric about
    zero would be invisible to it however severe.
    """
    index = np.arange(150, dtype=float)
    x = index / 25.0 - 3.0
    spread = 0.5 + 0.5 * (x + 3.0)
    return pd.DataFrame({"x": x, "y": 1.0 + 0.5 * x + spread * np.cos(2.0 * index)})


@pytest.fixture
def orthogonal() -> pd.DataFrame:
    """Two exactly orthogonal regressors: every VIF is 1 by construction."""
    pattern = np.array([[1.0, 1.0], [1.0, -1.0], [-1.0, 1.0], [-1.0, -1.0]])
    grid = np.tile(pattern, (10, 1))
    x1, x2 = grid[:, 0], grid[:, 1]
    wobble = 0.25 * np.cos(np.arange(len(grid), dtype=float))
    return pd.DataFrame({"x1": x1, "x2": x2, "y": 2.0 + 3.0 * x1 - x2 + wobble})


@pytest.fixture
def logistic_2x2() -> pd.DataFrame:
    """A 2x2 table whose logit has closed-form everything.

        arm A: 30 yes / 20 no   -> odds 1.5
        arm B: 10 yes / 40 no   -> odds 0.25

    Fitting an intercept plus one dummy saturates the model, so the maximum
    likelihood estimates reproduce the table exactly: the intercept is log(1.5),
    the coefficient on arm[B] is log(1/6), and its standard error is the
    textbook sqrt(sum of reciprocal cell counts).
    """
    return pd.DataFrame(
        {
            "arm": ["A"] * 50 + ["B"] * 50,
            "outcome": ["yes"] * 30 + ["no"] * 20 + ["yes"] * 10 + ["no"] * 40,
        }
    )


LOG_ODDS_B = math.log((10 / 40) / (30 / 20))
SE_LOG_ODDS_B = math.sqrt(1 / 30 + 1 / 20 + 1 / 10 + 1 / 40)


def _binary_entropy(p: float, n: int) -> float:
    return n * (p * math.log(p) + (1 - p) * math.log(1 - p))


@pytest.fixture
def separable() -> pd.DataFrame:
    """The outcome is a step function of x, so no finite coefficient exists."""
    x = np.arange(-20.0, 20.0)
    return pd.DataFrame({"x": x, "outcome": np.where(x > 0, "yes", "no")})


@pytest.fixture
def overdispersed_counts() -> pd.DataFrame:
    """A saturated Poisson layout, so the Pearson chi-square is arithmetic.

        arm A: ten 0s, ten 5s, ten 10s  -> mean  5, sum (y-5)^2  =  500 -> 100
        arm B: ten 2s, ten 10s, ten 18s -> mean 10, sum (y-10)^2 = 1280 -> 128

    Pearson chi-square 228 on 60 - 2 = 58 residual degrees of freedom.
    """
    return pd.DataFrame(
        {
            "arm": ["A"] * 30 + ["B"] * 30,
            "events": [0.0] * 10
            + [5.0] * 10
            + [10.0] * 10
            + [2.0] * 10
            + [10.0] * 10
            + [18.0] * 10,
        }
    )


@pytest.fixture
def equidispersed_counts() -> pd.DataFrame:
    """Same layout, spread consistent with a Poisson.

        arm A: ten 3s, ten 5s, ten 7s   -> mean  5, sum (y-5)^2  =  80 -> 16
        arm B: ten 7s, ten 10s, ten 13s -> mean 10, sum (y-10)^2 = 180 -> 18

    Pearson chi-square 34 on 58 df — a ratio well below 1.
    """
    return pd.DataFrame(
        {
            "arm": ["A"] * 30 + ["B"] * 30,
            "events": [3.0] * 10 + [5.0] * 10 + [7.0] * 10 + [7.0] * 10 + [10.0] * 10 + [13.0] * 10,
        }
    )


@pytest.fixture
def quantile_data() -> pd.DataFrame:
    """Eleven symmetric disturbances at each of twenty x values.

    The same disturbance set appears at every x and sums to zero, so the
    conditional mean and the conditional median both sit exactly on
    y = 2 + 3x. A tau = 0.5 fit that misses that line is wrong rather than
    unlucky, and the 0.9 quantile of the disturbances is exactly 2.0.
    """
    offsets = np.array([-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    x = np.repeat(np.arange(20, dtype=float) / 2.0, offsets.size)
    return pd.DataFrame({"x": x, "y": 2.0 + 3.0 * x + np.tile(offsets, 20)})


# ---------------------------------------------------------------------------
# OLS
# ---------------------------------------------------------------------------


class TestOlsAgainstLeastSquares:
    def test_coefficients_match_a_numpy_solve(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "x2"], "robust": "none"})
        beta, _ = _least_squares(linear, ["x1", "x2"])
        terms = _terms(result)

        assert terms[INTERCEPT]["coefficient"] == pytest.approx(beta[0], abs=1e-5)
        assert terms["x1"]["coefficient"] == pytest.approx(beta[1], abs=1e-5)
        assert terms["x2"]["coefficient"] == pytest.approx(beta[2], abs=1e-5)
        # And the generating process is recovered to within the wobble.
        assert terms["x1"]["coefficient"] == pytest.approx(2.0, abs=0.05)
        assert terms["x2"]["coefficient"] == pytest.approx(-1.5, abs=0.2)

    def test_fit_statistics_follow_from_the_residuals(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "x2"], "robust": "none"})
        _, residuals = _least_squares(linear, ["x1", "x2"])
        y = linear["y"].to_numpy(dtype=float)

        ss_residual = float(residuals @ residuals)
        ss_total = float(((y - y.mean()) ** 2).sum())
        r_squared = 1 - ss_residual / ss_total

        assert result.n == N_LINEAR
        assert result.stats["df_resid"] == N_LINEAR - 3
        assert result.stats["r_squared"] == pytest.approx(r_squared, abs=1e-6)
        assert result.stats["adj_r_squared"] == pytest.approx(
            1 - (1 - r_squared) * (N_LINEAR - 1) / (N_LINEAR - 3), abs=1e-6
        )
        assert result.stats["rmse"] == pytest.approx(math.sqrt(ss_residual / N_LINEAR), abs=1e-6)
        assert result.stats["residual_std_error"] == pytest.approx(
            math.sqrt(ss_residual / (N_LINEAR - 3)), abs=1e-6
        )

    def test_classical_standard_errors_match_the_closed_form(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "x2"], "robust": "none"})
        _, residuals = _least_squares(linear, ["x1", "x2"])
        design = np.column_stack(
            [np.ones(N_LINEAR), linear["x1"].to_numpy(), linear["x2"].to_numpy()]
        )
        sigma_squared = float(residuals @ residuals) / (N_LINEAR - 3)
        expected = np.sqrt(np.diag(np.linalg.inv(design.T @ design) * sigma_squared))

        terms = _terms(result)
        for name, value in zip([INTERCEPT, "x1", "x2"], expected, strict=True):
            assert terms[name]["std_err"] == pytest.approx(float(value), abs=1e-6)

    def test_the_f_test_matches_r_squared(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "x2"], "robust": "none"})
        r_squared = result.stats["r_squared"]
        # F = (R^2/k) / ((1-R^2)/(n-k-1)) for a classical fit with an intercept.
        expected = (r_squared / 2) / ((1 - r_squared) / (N_LINEAR - 3))
        assert result.stats["f_statistic"] == pytest.approx(expected, rel=1e-4)
        assert 0.0 < result.stats["f_p_value"] < 1e-6


class TestOlsCategoricalRegressors:
    def test_dummies_are_named_and_the_baseline_is_stated(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "region"]})
        terms = _terms(result)

        assert "region[North]" in terms
        assert "region[West]" in terms
        # The alphabetically first level is the reference and gets no column.
        assert "region[East]" not in terms
        assert result.stats["reference_levels"] == {"region": "East"}
        assert any("region = 'East'" in note for note in result.notes)

    def test_a_categorical_with_too_many_levels_is_refused(self):
        frame = pd.DataFrame(
            {
                "y": [float(v % 7) for v in range(120)],
                "code": [f"L{v % 40}" for v in range(120)],
            }
        )
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "ols", {"y": "y", "x": ["code"]})
        message = str(excinfo.value)
        assert "40" in message
        assert "code" in message


class TestOlsRobustStandardErrors:
    def test_hc3_is_at_least_hc0_and_both_differ_from_classical(self, heteroskedastic):
        params = {"y": "y", "x": ["x"]}
        classical = _terms(_run(heteroskedastic, "ols", {**params, "robust": "none"}))
        hc0 = _terms(_run(heteroskedastic, "ols", {**params, "robust": "HC0"}))
        hc3 = _terms(_run(heteroskedastic, "ols", {**params, "robust": "HC3"}))

        assert hc0["x"]["std_err"] != pytest.approx(classical["x"]["std_err"], rel=1e-3)
        # HC3 inflates each squared residual by 1/(1-h)^2, so it is never narrower.
        assert hc3["x"]["std_err"] >= hc0["x"]["std_err"]
        assert hc3[INTERCEPT]["std_err"] >= hc0[INTERCEPT]["std_err"]
        # The covariance choice never moves the point estimate.
        assert hc3["x"]["coefficient"] == pytest.approx(classical["x"]["coefficient"], abs=1e-9)

    def test_hc3_is_the_default(self, heteroskedastic):
        result = _run(heteroskedastic, "ols", {"y": "y", "x": ["x"]})
        assert result.stats["standard_errors"] == "HC3"

    def test_heteroskedasticity_is_reported(self, heteroskedastic):
        result = _run(heteroskedastic, "ols", {"y": "y", "x": ["x"], "robust": "none"})
        check = _assumption(result, "breusch")
        assert check["passed"] is False
        assert check["p_value"] is not None and check["p_value"] < 0.05


class TestOlsDiagnostics:
    def test_vif_is_one_for_orthogonal_regressors(self, orthogonal):
        result = _run(orthogonal, "ols", {"y": "y", "x": ["x1", "x2"]})
        vif = {row["term"]: row["vif"] for row in result.stats["vif"]}

        assert vif["x1"] == pytest.approx(1.0, abs=1e-6)
        assert vif["x2"] == pytest.approx(1.0, abs=1e-6)
        assert _assumption(result, "multicollinearity")["passed"] is True

    def test_vif_explodes_for_a_near_duplicate_regressor(self, orthogonal):
        frame = orthogonal.assign(x3=orthogonal["x1"] + 0.01 * orthogonal["x2"])
        result = _run(frame, "ols", {"y": "y", "x": ["x1", "x3"]})
        vif = {row["term"]: row["vif"] for row in result.stats["vif"]}

        assert vif["x1"] > 100
        assert vif["x3"] > 100
        check = _assumption(result, "multicollinearity")
        assert check["passed"] is False

    def test_every_diagnostic_is_reported(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "x2"]})
        for needle in ("multicollinearity", "breusch", "durbin", "jarque", "cook"):
            check = _assumption(result, needle)
            assert set(check) == {"name", "passed", "detail", "statistic", "p_value"}
            assert check["passed"] in (True, False, None)

    def test_influence_counts_observations_above_four_over_n(self, linear):
        result = _run(linear, "ols", {"y": "y", "x": ["x1", "x2"]})
        check = _assumption(result, "cook")
        assert 0.0 <= check["statistic"] <= 1.0
        assert "4/n" in check["detail"]


class TestOlsRefusals:
    def test_too_few_rows_for_the_parameters(self, linear):
        with pytest.raises(ExecutionError) as excinfo:
            _run(linear.head(3), "ols", {"y": "y", "x": ["x1", "x2"]})
        message = str(excinfo.value)
        assert "3" in message and "parameter" in message.lower()

    def test_a_constant_regressor(self, linear):
        frame = linear.assign(flat=1.0)
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "ols", {"y": "y", "x": ["x1", "flat"]})
        assert "flat" in str(excinfo.value)

    def test_perfectly_collinear_regressors(self, linear):
        frame = linear.assign(twice=2.0 * linear["x1"] + 5.0)
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "ols", {"y": "y", "x": ["x1", "twice"]})
        message = str(excinfo.value)
        assert "twice" in message
        assert "collinear" in message.lower()

    def test_the_outcome_cannot_also_be_a_regressor(self, linear):
        with pytest.raises(ExecutionError) as excinfo:
            _run(linear, "ols", {"y": "y", "x": ["y", "x1"]})
        assert "'y'" in str(excinfo.value)

    def test_a_numerically_perfect_fit_is_refused(self):
        # y is an exact linear function of x, so the residuals are rounding
        # noise and every standard error, t and p below is an artifact of it.
        frame = pd.DataFrame({"x": np.arange(40.0), "y": 3.0 + 2.0 * np.arange(40.0)})
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "ols", {"y": "y", "x": ["x"]})
        message = str(excinfo.value)
        assert "1.0" in message or "1.000" in message

    def test_missing_rows_are_dropped_listwise_and_counted(self, linear):
        frame = linear.copy()
        frame.loc[0:4, "x2"] = np.nan
        frame.loc[10, "y"] = np.nan
        result = _run(frame, "ols", {"y": "y", "x": ["x1", "x2"]})

        assert result.n == N_LINEAR - 6
        assert result.n_excluded == 6
        assert any("listwise" in note.lower() for note in result.notes)
        assert any("6" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Logit
# ---------------------------------------------------------------------------


class TestLogit:
    def test_the_saturated_fit_reproduces_the_table(self, logistic_2x2):
        result = _run(logistic_2x2, "logit", {"y": "outcome", "success_value": "yes", "x": ["arm"]})
        terms = _terms(result)

        assert terms[INTERCEPT]["coefficient"] == pytest.approx(math.log(1.5), abs=1e-6)
        assert terms["arm[B]"]["coefficient"] == pytest.approx(LOG_ODDS_B, abs=1e-6)
        assert terms["arm[B]"]["coefficient"] < 0  # arm B has the lower odds
        assert terms["arm[B]"]["std_err"] == pytest.approx(SE_LOG_ODDS_B, abs=1e-6)
        assert terms["arm[B]"]["odds_ratio"] == pytest.approx(1 / 6, abs=1e-6)
        assert result.stats["reference_levels"] == {"arm": "A"}

    def test_the_odds_ratio_interval_is_the_exponentiated_log_odds_interval(self, logistic_2x2):
        result = _run(logistic_2x2, "logit", {"y": "outcome", "success_value": "yes", "x": ["arm"]})
        row = _terms(result)["arm[B]"]

        expected_low = LOG_ODDS_B - Z_95 * SE_LOG_ODDS_B
        expected_high = LOG_ODDS_B + Z_95 * SE_LOG_ODDS_B
        assert row["ci_low"] == pytest.approx(expected_low, abs=1e-5)
        assert row["ci_high"] == pytest.approx(expected_high, abs=1e-5)
        assert row["or_ci_low"] == pytest.approx(math.exp(expected_low), abs=1e-5)
        assert row["or_ci_high"] == pytest.approx(math.exp(expected_high), abs=1e-5)
        # The interval excludes 1, matching a coefficient interval excluding 0.
        assert row["or_ci_high"] < 1.0

    def test_fit_statistics_match_the_binomial_log_likelihoods(self, logistic_2x2):
        result = _run(logistic_2x2, "logit", {"y": "outcome", "success_value": "yes", "x": ["arm"]})
        log_likelihood = _binary_entropy(0.6, 50) + _binary_entropy(0.2, 50)
        null_log_likelihood = _binary_entropy(0.4, 100)

        assert result.n == 100
        assert result.stats["base_rate"] == pytest.approx(0.4, abs=1e-9)
        assert result.stats["log_likelihood"] == pytest.approx(log_likelihood, abs=1e-5)
        assert result.stats["null_log_likelihood"] == pytest.approx(null_log_likelihood, abs=1e-5)
        assert result.stats["pseudo_r_squared"] == pytest.approx(
            1 - log_likelihood / null_log_likelihood, abs=1e-6
        )
        assert 0.0 < result.stats["llr_p_value"] < 0.001

    def test_separation_is_refused_rather_than_reported(self, separable):
        with pytest.raises(ExecutionError) as excinfo:
            _run(separable, "logit", {"y": "outcome", "success_value": "yes", "x": ["x"]})
        assert "separat" in str(excinfo.value).lower()

    def test_an_outcome_with_no_variation_is_refused(self, logistic_2x2):
        frame = logistic_2x2.assign(outcome="yes")
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "logit", {"y": "outcome", "success_value": "yes", "x": ["arm"]})
        message = str(excinfo.value)
        assert "100" in message  # every one of the 100 rows is a success

    def test_a_success_value_that_never_occurs_is_refused(self, logistic_2x2):
        with pytest.raises(ExecutionError) as excinfo:
            _run(logistic_2x2, "logit", {"y": "outcome", "success_value": "maybe", "x": ["arm"]})
        message = str(excinfo.value)
        assert "maybe" in message
        assert "yes" in message  # the real categories are listed

    def test_assumptions_include_events_per_predictor(self, logistic_2x2):
        result = _run(logistic_2x2, "logit", {"y": "outcome", "success_value": "yes", "x": ["arm"]})
        check = _assumption(result, "events per")
        assert check["passed"] is True
        assert check["statistic"] == pytest.approx(40.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Count models
# ---------------------------------------------------------------------------


class TestCountModel:
    def test_the_saturated_poisson_returns_group_means(self, overdispersed_counts):
        result = _run(overdispersed_counts, "count_model", {"y": "events", "x": ["arm"]})
        terms = _terms(result)

        assert terms[INTERCEPT]["coefficient"] == pytest.approx(math.log(5.0), abs=1e-6)
        assert terms["arm[B]"]["coefficient"] == pytest.approx(math.log(2.0), abs=1e-6)
        assert terms["arm[B]"]["irr"] == pytest.approx(2.0, abs=1e-6)
        assert terms["arm[B]"]["irr_ci_low"] == pytest.approx(
            math.exp(terms["arm[B]"]["ci_low"]), abs=1e-5
        )

    def test_overdispersion_is_measured_and_flagged(self, overdispersed_counts):
        result = _run(overdispersed_counts, "count_model", {"y": "events", "x": ["arm"]})
        check = _assumption(result, "overdispersion")

        # Pearson chi-square 228 on 58 residual degrees of freedom.
        assert check["statistic"] == pytest.approx(228 / 58, abs=1e-6)
        assert check["passed"] is False
        assert set(check) == {"name", "passed", "detail", "statistic", "p_value"}
        assert any("negative_binomial" in note for note in result.notes)

    def test_equidispersed_counts_are_not_flagged(self, equidispersed_counts):
        result = _run(equidispersed_counts, "count_model", {"y": "events", "x": ["arm"]})
        check = _assumption(result, "overdispersion")

        assert check["statistic"] == pytest.approx(34 / 58, abs=1e-6)
        assert check["passed"] is True
        assert not any("negative_binomial" in note for note in result.notes)

    def test_the_negative_binomial_alternative_estimates_a_dispersion(self, overdispersed_counts):
        result = _run(
            overdispersed_counts,
            "count_model",
            {"y": "events", "x": ["arm"], "family": "negative_binomial"},
        )
        terms = _terms(result)

        # The NB2 score equations for the mean parameters are also satisfied at
        # the group means, so the rate ratio is unchanged; only the spread moves.
        assert terms["arm[B]"]["irr"] == pytest.approx(2.0, abs=1e-4)
        assert result.stats["dispersion"]["alpha"] > 0.0
        assert "alpha" not in terms
        assert terms["arm[B]"]["std_err"] > 0.0

    def test_exposure_enters_as_a_log_offset(self, overdispersed_counts):
        # Arm B has twice the events and twice the exposure, so its rate ratio
        # against arm A is exactly one once the offset is applied.
        frame = overdispersed_counts.assign(
            days=np.where(overdispersed_counts["arm"] == "B", 2.0, 1.0)
        )
        result = _run(frame, "count_model", {"y": "events", "x": ["arm"], "exposure": "days"})
        row = _terms(result)["arm[B]"]

        assert row["coefficient"] == pytest.approx(0.0, abs=1e-6)
        assert row["irr"] == pytest.approx(1.0, abs=1e-6)

    def test_a_negative_outcome_is_refused(self, overdispersed_counts):
        frame = overdispersed_counts.copy()
        frame.loc[0, "events"] = -3.0
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "count_model", {"y": "events", "x": ["arm"]})
        assert "-3" in str(excinfo.value)

    def test_a_non_positive_exposure_is_refused(self, overdispersed_counts):
        frame = overdispersed_counts.assign(days=0.0)
        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "count_model", {"y": "events", "x": ["arm"], "exposure": "days"})
        assert "days" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Quantile regression
# ---------------------------------------------------------------------------


def _share_below(df: pd.DataFrame, result: Any) -> float:
    terms = _terms(result)
    fitted = terms[INTERCEPT]["coefficient"] + terms["x"]["coefficient"] * df["x"].to_numpy()
    return float(np.mean(df["y"].to_numpy() - fitted < -1e-9))


class TestQuantileRegression:
    def test_the_median_fit_lands_on_the_ols_line(self, quantile_data):
        median = _terms(_run(quantile_data, "quantile_regression", {"y": "y", "x": ["x"]}))
        ols = _terms(_run(quantile_data, "ols", {"y": "y", "x": ["x"]}))

        assert median["x"]["coefficient"] == pytest.approx(ols["x"]["coefficient"], abs=0.01)
        assert median[INTERCEPT]["coefficient"] == pytest.approx(
            ols[INTERCEPT]["coefficient"], abs=0.05
        )
        # Both recover the line the fixture was built from.
        assert median["x"]["coefficient"] == pytest.approx(3.0, abs=0.01)
        assert median[INTERCEPT]["coefficient"] == pytest.approx(2.0, abs=0.05)

    def test_the_default_tau_is_the_median(self, quantile_data):
        result = _run(quantile_data, "quantile_regression", {"y": "y", "x": ["x"]})
        assert result.stats["tau"] == pytest.approx(0.5, abs=1e-9)

    def test_a_higher_quantile_lies_above_the_median_fit(self, quantile_data):
        median = _run(quantile_data, "quantile_regression", {"y": "y", "x": ["x"]})
        upper = _run(quantile_data, "quantile_regression", {"y": "y", "x": ["x"], "tau": 0.9})

        mean_x = float(quantile_data["x"].mean())
        at = lambda terms: terms[INTERCEPT]["coefficient"] + terms["x"]["coefficient"] * mean_x  # noqa: E731
        assert at(_terms(upper)) > at(_terms(median)) + 0.5

        # A tau-quantile fit leaves roughly tau of the sample beneath it.
        assert 0.40 <= _share_below(quantile_data, median) <= 0.60
        assert 0.78 <= _share_below(quantile_data, upper) <= 0.96  # 9 of 11 offsets

    def test_an_extreme_tau_on_a_small_sample_is_flagged(self):
        frame = pd.DataFrame(
            {"x": np.arange(20.0), "y": np.arange(20.0) * 2 + 1 + np.cos(np.arange(20.0))}
        )
        result = _run(frame, "quantile_regression", {"y": "y", "x": ["x"], "tau": 0.95})
        check = _assumption(result, "observations")
        assert check["passed"] is False


# ---------------------------------------------------------------------------
# Validation rules declared beside the operations
# ---------------------------------------------------------------------------


class TestDeclaredRules:
    def test_the_outcome_may_not_appear_among_the_regressors(self, linear):
        problems = _validate(linear, "ols", {"y": "y", "x": ["y", "x1"]})
        assert problems and any("'y'" in problem for problem in problems)

    def test_a_repeated_regressor_is_rejected(self, linear):
        problems = _validate(linear, "ols", {"y": "y", "x": ["x1", "x1"]})
        assert problems and any("x1" in problem for problem in problems)

    def test_a_success_value_absent_from_the_outcome_is_rejected(self, logistic_2x2):
        problems = _validate(
            logistic_2x2, "logit", {"y": "outcome", "success_value": "maybe", "x": ["arm"]}
        )
        assert problems
        assert any("maybe" in problem and "yes" in problem for problem in problems)

    def test_a_high_cardinality_categorical_is_rejected_up_front(self):
        frame = pd.DataFrame(
            {"y": [float(v % 7) for v in range(120)], "code": [f"L{v % 40}" for v in range(120)]}
        )
        problems = _validate(frame, "ols", {"y": "y", "x": ["code"]})
        assert problems and any("40" in problem for problem in problems)

    def test_a_datetime_regressor_is_rejected(self, linear):
        frame = linear.assign(
            when=pd.to_datetime("2026-01-01") + pd.to_timedelta(np.arange(N_LINEAR), unit="D")
        )
        problems = _validate(frame, "ols", {"y": "y", "x": ["when"]})
        assert problems and any("when" in problem for problem in problems)

    def test_exposure_may_not_be_the_outcome(self, overdispersed_counts):
        problems = _validate(
            overdispersed_counts,
            "count_model",
            {"y": "events", "x": ["arm"], "exposure": "events"},
        )
        assert problems and any("exposure" in problem for problem in problems)

    def test_a_valid_spec_passes(self, linear):
        assert _validate(linear, "ols", {"y": "y", "x": ["x1", "region"]}) == []


# ---------------------------------------------------------------------------
# Registry and output contract
# ---------------------------------------------------------------------------


_CASES: dict[str, dict[str, Any]] = {
    "ols": {"y": "y", "x": ["x1", "x2"]},
    "logit": {"y": "outcome", "success_value": "yes", "x": ["arm"]},
    "count_model": {"y": "events", "x": ["arm"]},
    "quantile_regression": {"y": "y", "x": ["x1", "x2"]},
}


class TestRegistry:
    def test_every_declared_operation_has_a_handler(self):
        assert set(REGRESSION_OPERATION_DEFS) == set(REGRESSION_OPERATIONS)

    def test_every_operation_is_tier_four_with_a_summary(self):
        for name, definition in REGRESSION_OPERATION_DEFS.items():
            assert definition.tier == 4, name
            assert definition.summary.strip(), name
            assert definition.params, name

    def test_every_handler_is_callable(self):
        assert all(callable(handler) for handler in REGRESSION_OPERATIONS.values())

    def test_the_declared_operations_are_the_ones_this_tier_promises(self):
        assert set(REGRESSION_OPERATION_DEFS) == set(_CASES)

    def test_every_conditional_rule_has_prompt_text_and_a_check(self):
        for name, definition in REGRESSION_OPERATION_DEFS.items():
            assert definition.check is not None, name
            assert definition.requires.strip(), name


class TestOutputContract:
    @pytest.mark.parametrize("op", sorted(_CASES))
    def test_every_result_carries_assumptions_and_a_finite_n(
        self, op, linear, logistic_2x2, overdispersed_counts
    ):
        frames = {
            "ols": linear,
            "quantile_regression": linear,
            "logit": logistic_2x2,
            "count_model": overdispersed_counts,
        }
        result = _run(frames[op], op, _CASES[op])

        assert result.stats["assumptions"], op
        assert result.n > 0
        assert result.stats["effect_size"]["name"]
        assert result.columns[0] == "term"
        assert json.dumps(result.stats, allow_nan=False)

    @pytest.mark.parametrize("op", sorted(_CASES))
    def test_no_p_value_serializes_as_zero(self, op, linear, logistic_2x2, overdispersed_counts):
        frames = {
            "ols": linear,
            "quantile_regression": linear,
            "logit": logistic_2x2,
            "count_model": overdispersed_counts,
        }
        result = _run(frames[op], op, _CASES[op])

        found = _collect_p_values(result.stats)
        assert found, op
        assert all(p > 0.0 for p in found), (op, found)

        column = "p_value"
        assert column in result.columns
        index = result.columns.index(column)
        assert all(row[index] is None or row[index] > 0.0 for row in result.rows)
