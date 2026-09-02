"""Tier 5 time-series operations, against series whose truth is known.

Every fixture here is generated from a formula, so the answer is known before
the code runs: a line of slope 0.5 plus a sine of amplitude 10, an AR(1) with
phi = 0.7, a random walk that is non-stationary by construction, a series
built so that x leads y. The assertions compare against those constants and
against quantities computed independently of the implementation (the OLS
estimate of phi by hand, phi^k for the ACF), never against the module's own
output.

The irregular-input tests matter as much as the statistical ones. Real uploads
are not regularly spaced, and every operation here assumes they are — so what
the preparation step does to an uneven series, and how loudly it says so, is a
correctness surface.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.services.analysis_result import ExecutionError
from app.services.analysis_spec import RESAMPLE_FREQS
from app.services.analysis_timeseries import (
    TIMESERIES_OPERATION_DEFS,
    TIMESERIES_OPERATIONS,
    op_arima,
    op_autocorrelation,
    op_decompose,
    op_granger_causality,
    op_stationarity_test,
)
from app.services.analysis_timeseries_prep import (
    MAX_INPUT_ROWS,
    SERIES_FREQS,
    infer_frequency,
    prepare_series,
)

# ---------------------------------------------------------------------------
# Fixtures with known truth
# ---------------------------------------------------------------------------

TRUE_SLOPE = 0.5
TRUE_AMPLITUDE = 10.0
TRUE_PHI = 0.7
MONTHLY_PERIOD = 12


def _frame(dates: Any, **columns: Any) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.DatetimeIndex(dates), **columns})


def monthly_dates(n: int, start: str = "2010-01-31") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="ME")


def trend_plus_season(n: int = 180, noise: float = 1.0, seed: int = 3) -> pd.DataFrame:
    """0.5 * t + 10 * sin(2*pi*t/12) + noise, on a monthly grid."""
    t = np.arange(n, dtype=float)
    values = (
        TRUE_SLOPE * t
        + TRUE_AMPLITUDE * np.sin(2 * np.pi * t / MONTHLY_PERIOD)
        + np.random.default_rng(seed).normal(scale=noise, size=n)
    )
    return _frame(monthly_dates(n), value=values)


def white_noise(n: int = 300, seed: int = 13, freq: str = "D") -> pd.DataFrame:
    values = np.random.default_rng(seed).normal(size=n)
    return _frame(pd.date_range("2018-01-01", periods=n, freq=freq), value=values)


def ar1(n: int = 400, phi: float = TRUE_PHI, seed: int = 7, burn_in: int = 200) -> np.ndarray:
    """An AR(1) path, discarding a burn-in so the start is not special."""
    rng = np.random.default_rng(seed)
    total = n + burn_in
    shocks = rng.normal(size=total)
    path = np.zeros(total)
    for step in range(1, total):
        path[step] = phi * path[step - 1] + shocks[step]
    return path[burn_in:]


def ar1_frame(n: int = 400, **kwargs: Any) -> pd.DataFrame:
    return _frame(pd.date_range("2015-01-01", periods=n, freq="D"), value=ar1(n, **kwargs))


def random_walk(n: int = 300, seed: int = 23) -> pd.DataFrame:
    values = np.cumsum(np.random.default_rng(seed).normal(size=n))
    return _frame(pd.date_range("2018-01-01", periods=n, freq="D"), value=values)


def leading_pair(n: int = 250, seed: int = 11, strength: float = 0.8) -> pd.DataFrame:
    """cause[t-1] drives value[t] — Granger precedence by construction."""
    rng = np.random.default_rng(seed)
    cause = rng.normal(size=n)
    value = np.zeros(n)
    for step in range(1, n):
        value[step] = strength * cause[step - 1] + rng.normal(scale=0.5)
    return _frame(pd.date_range("2019-01-01", periods=n, freq="D"), value=value, cause=cause)


def independent_pair(n: int = 250, seed: int = 31) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return _frame(
        pd.date_range("2019-01-01", periods=n, freq="D"),
        value=rng.normal(size=n),
        cause=rng.normal(size=n),
    )


def _p_values(payload: Any, found: list[float] | None = None) -> list[float]:
    """Every value under a key that looks like a p-value, at any depth."""
    collected = [] if found is None else found
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "p_value" in key or key == "pvalue":
                    collected.append(float(value))
            _p_values(value, collected)
    elif isinstance(payload, list):
        for item in payload:
            _p_values(item, collected)
    return collected


def _column(result: Any, name: str) -> list[Any]:
    return [row[result.columns.index(name)] for row in result.rows]


# ---------------------------------------------------------------------------
# Registry contract
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_every_definition_has_a_handler_and_every_handler_a_definition(self):
        assert set(TIMESERIES_OPERATION_DEFS) == set(TIMESERIES_OPERATIONS)

    def test_all_operations_are_tier_five(self):
        assert {d.tier for d in TIMESERIES_OPERATION_DEFS.values()} == {5}

    def test_expected_operations_are_declared(self):
        assert set(TIMESERIES_OPERATION_DEFS) == {
            "decompose",
            "stationarity_test",
            "autocorrelation",
            "arima",
            "granger_causality",
        }

    def test_frequency_choices_match_the_validator(self):
        # The prompt renders these choices; the validator enforces
        # RESAMPLE_FREQS. Drift between them would advertise a frequency the
        # validator rejects.
        assert set(SERIES_FREQS) == set(RESAMPLE_FREQS)

    def test_declared_frequency_choices_are_the_shared_set(self):
        for definition in TIMESERIES_OPERATION_DEFS.values():
            freq = next(p for p in definition.params if p.name == "freq")
            assert set(freq.choices) == set(SERIES_FREQS)

    def test_differencing_orders_accept_zero(self):
        # d and D are non-negative, not positive: ARIMA(1,0,0) is a valid order.
        arima = TIMESERIES_OPERATION_DEFS["arima"]
        kinds = {param.name: param.kind for param in arima.params}
        assert kinds["d"] == "count"
        assert kinds["D"] == "count"

    def test_seasonal_orders_require_a_seasonal_period(self):
        arima = TIMESERIES_OPERATION_DEFS["arima"]
        assert arima.check is not None
        problems = arima.check({"p": 1, "d": 0, "q": 0, "P": 1}, None)
        assert any("seasonal_period" in problem for problem in problems)
        assert arima.check({"p": 1, "d": 0, "q": 0, "P": 1, "seasonal_period": 12}, None) == []

    def test_forecast_periods_is_only_an_arima_parameter(self):
        for name, definition in TIMESERIES_OPERATION_DEFS.items():
            names = {param.name for param in definition.params}
            assert ("forecast_periods" in names) == (name == "arima")


# ---------------------------------------------------------------------------
# Regular-grid preparation
# ---------------------------------------------------------------------------


class TestPreparation:
    def test_duplicate_timestamps_are_collapsed_and_counted(self):
        dates = pd.DatetimeIndex(
            ["2020-01-01", "2020-01-01", "2020-01-01", "2020-01-02", "2020-01-03"]
        )
        df = _frame(dates, value=[1.0, 2.0, 3.0, 10.0, 20.0])
        prepared = prepare_series(
            df,
            {"date": "date", "value": "value", "freq": "D"},
            op="test",
            minimum_periods=2,
        )

        assert prepared.n_duplicate_timestamps == 2
        assert prepared.n_periods == 3
        # Collapsed by the mean of 1, 2, 3.
        assert prepared.series("value")[0] == pytest.approx(2.0)
        assert any("duplicate" in note.lower() for note in prepared.notes())

    def test_named_aggregation_rule_collapses_duplicates(self):
        dates = pd.DatetimeIndex(["2020-01-01", "2020-01-01", "2020-01-02"])
        df = _frame(dates, value=[1.0, 3.0, 10.0])
        prepared = prepare_series(
            df,
            {"date": "date", "value": "value", "freq": "D", "agg": "sum"},
            op="test",
            minimum_periods=2,
        )
        assert prepared.series("value")[0] == pytest.approx(4.0)
        assert prepared.agg == "sum"

    def test_gaps_are_filled_counted_and_named(self):
        # A daily grid of 20 days with days 5 and 11 absent.
        full = pd.date_range("2020-01-01", periods=20, freq="D")
        keep = full.delete([5, 11])
        df = _frame(keep, value=np.arange(len(keep), dtype=float))
        prepared = prepare_series(df, {"date": "date", "value": "value"}, op="test")

        assert prepared.n_periods == 20
        assert prepared.n_empty_periods == 2
        assert prepared.n_interpolated == 2
        assert any("interpolat" in note.lower() for note in prepared.notes())
        assumption = prepared.assumption()
        assert assumption.passed is False
        assert "2" in assumption.detail

    def test_a_regularly_spaced_series_passes_the_spacing_assumption(self):
        prepared = prepare_series(white_noise(50), {"date": "date", "value": "value"}, op="test")
        assert prepared.n_interpolated == 0
        assert prepared.assumption().passed is True

    def test_mostly_gaps_is_refused_and_names_resample(self):
        # 14 observations scattered over 200 days: 93% of the grid is absent.
        rng = np.random.default_rng(2)
        offsets = np.sort(rng.choice(np.arange(200), size=14, replace=False))
        dates = pd.Timestamp("2020-01-01") + pd.to_timedelta(offsets, unit="D")
        df = _frame(dates, value=np.arange(14, dtype=float))

        with pytest.raises(ExecutionError) as excinfo:
            prepare_series(df, {"date": "date", "value": "value", "freq": "D"}, op="decompose")
        assert "resample" in str(excinfo.value)

    def test_too_few_periods_is_refused(self):
        df = _frame(pd.date_range("2020-01-01", periods=4, freq="D"), value=[1.0, 2.0, 3.0, 4.0])
        with pytest.raises(ExecutionError):
            prepare_series(df, {"date": "date", "value": "value", "freq": "D"}, op="decompose")

    def test_oversized_input_is_refused_and_names_resample(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.analysis_timeseries_prep.MAX_INPUT_ROWS",
            10,
        )
        with pytest.raises(ExecutionError) as excinfo:
            prepare_series(white_noise(50), {"date": "date", "value": "value"}, op="arima")
        assert "resample" in str(excinfo.value)
        assert str(MAX_INPUT_ROWS)  # the real cap is a named constant

    def test_oversized_grid_is_refused(self, monkeypatch):
        monkeypatch.setattr("app.services.analysis_timeseries_prep.MAX_SERIES_PERIODS", 20)
        with pytest.raises(ExecutionError) as excinfo:
            prepare_series(white_noise(50), {"date": "date", "value": "value"}, op="arima")
        assert "resample" in str(excinfo.value)

    def test_rows_missing_the_date_or_the_value_are_excluded(self):
        dates = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03", None])
        df = _frame(dates, value=[1.0, 2.0, np.nan, 4.0])
        prepared = prepare_series(
            df, {"date": "date", "value": "value", "freq": "D"}, op="test", minimum_periods=2
        )
        assert prepared.n_excluded == 2
        assert prepared.n_used == 2

    def test_frequency_is_inferred_with_stated_evidence(self):
        prepared = prepare_series(
            trend_plus_season(60), {"date": "date", "value": "value"}, op="test"
        )
        assert prepared.freq == "ME"
        assert prepared.freq_evidence

    def test_inference_falls_back_to_median_spacing(self):
        # Irregular monthly-ish stamps: pandas cannot name an offset alias, so
        # the median spacing has to decide.
        dates = pd.DatetimeIndex(
            ["2020-01-03", "2020-02-07", "2020-03-02", "2020-04-11", "2020-05-05"]
        )
        freq, evidence = infer_frequency(dates)
        assert freq == "ME"
        assert "spacing" in evidence.lower()

    def test_declared_frequency_overrides_inference(self):
        prepared = prepare_series(
            trend_plus_season(60), {"date": "date", "value": "value", "freq": "QE"}, op="test"
        )
        assert prepared.freq == "QE"
        assert "requested" in prepared.freq_evidence.lower()


# ---------------------------------------------------------------------------
# decompose
# ---------------------------------------------------------------------------


class TestDecompose:
    def test_recovers_the_known_trend_slope(self):
        result = op_decompose(
            trend_plus_season(), {"date": "date", "value": "value"}, "Decomposition"
        )
        slope = result.stats["trend_slope_per_period"]
        assert slope == pytest.approx(TRUE_SLOPE, abs=0.05)

    def test_recovers_the_known_seasonal_amplitude(self):
        result = op_decompose(trend_plus_season(), {"date": "date", "value": "value"}, "D")
        amplitude = result.stats["seasonal_amplitude"]
        assert amplitude == pytest.approx(TRUE_AMPLITUDE, rel=0.15)

    def test_seasonality_strength_is_high_for_a_seasonal_series(self):
        result = op_decompose(trend_plus_season(), {"date": "date", "value": "value"}, "D")
        assert result.stats["seasonal_strength"] > 0.8
        assert result.stats["trend_strength"] > 0.8

    def test_seasonality_strength_is_near_zero_for_noise(self):
        noise = _frame(monthly_dates(180), value=np.random.default_rng(13).normal(size=180))
        result = op_decompose(noise, {"date": "date", "value": "value"}, "D")
        assert result.stats["seasonal_strength"] < 0.2
        assert result.stats["trend_strength"] < 0.2

    def test_strengths_are_clipped_to_the_unit_interval(self):
        result = op_decompose(trend_plus_season(), {"date": "date", "value": "value"}, "D")
        for key in ("trend_strength", "seasonal_strength"):
            assert 0.0 <= result.stats[key] <= 1.0

    def test_result_table_carries_the_four_components(self):
        result = op_decompose(trend_plus_season(60), {"date": "date", "value": "value"}, "D")
        assert result.columns == ["date", "observed", "trend", "seasonal", "residual"]
        assert result.total_rows == 60

    def test_short_series_uses_classical_decomposition(self):
        # Two full cycles but not three: STL is not credible, classical is.
        result = op_decompose(trend_plus_season(28), {"date": "date", "value": "value"}, "D")
        assert "classical" in result.stats["method"].lower()

    def test_refuses_a_series_shorter_than_two_cycles(self):
        with pytest.raises(ExecutionError) as excinfo:
            op_decompose(trend_plus_season(18), {"date": "date", "value": "value"}, "D")
        assert "seasonal" in str(excinfo.value).lower()

    def test_yearly_data_requires_an_explicit_seasonal_period(self):
        yearly = _frame(
            pd.date_range("1980-12-31", periods=40, freq="YE"),
            value=np.arange(40, dtype=float),
        )
        with pytest.raises(ExecutionError) as excinfo:
            op_decompose(yearly, {"date": "date", "value": "value"}, "D")
        assert "seasonal_period" in str(excinfo.value)

    def test_reports_assumptions_and_sample_size(self):
        result = op_decompose(trend_plus_season(), {"date": "date", "value": "value"}, "D")
        names = {check["name"] for check in result.stats["assumptions"]}
        assert any("spacing" in name.lower() for name in names)
        assert result.n == 180
        assert result.stats["effect_size"]["magnitude"]
        assert result.stats["confidence_interval"]["low"] is not None


# ---------------------------------------------------------------------------
# stationarity_test
# ---------------------------------------------------------------------------


class TestStationarity:
    def test_random_walk_fails_adf_and_fails_kpss_stationarity(self):
        result = op_stationarity_test(random_walk(), {"date": "date", "value": "value"}, "S")
        assert result.stats["adf"]["rejects_unit_root"] is False
        assert result.stats["kpss"]["rejects_stationarity"] is True
        assert result.stats["verdict_code"] == "unit_root"
        assert "unit root" in result.stats["verdict"].lower()

    def test_white_noise_passes_adf_and_kpss(self):
        result = op_stationarity_test(white_noise(), {"date": "date", "value": "value"}, "S")
        assert result.stats["adf"]["rejects_unit_root"] is True
        assert result.stats["kpss"]["rejects_stationarity"] is False
        assert result.stats["verdict_code"] == "stationary"
        assert "stationary" in result.stats["verdict"].lower()

    def test_every_verdict_combination_has_wording(self):
        from app.services.analysis_timeseries import JOINT_VERDICTS

        assert set(JOINT_VERDICTS) == {
            (True, False),
            (False, True),
            (True, True),
            (False, False),
        }
        codes = {code for code, _ in JOINT_VERDICTS.values()}
        assert codes == {"stationary", "unit_root", "trend_stationary", "inconclusive"}

    def test_random_walk_needs_one_difference(self):
        result = op_stationarity_test(random_walk(), {"date": "date", "value": "value"}, "S")
        assert result.stats["differences_suggested"] == 1

    def test_stationary_series_needs_no_differences(self):
        result = op_stationarity_test(white_noise(), {"date": "date", "value": "value"}, "S")
        assert result.stats["differences_suggested"] == 0

    def test_critical_values_are_reported_for_both_tests(self):
        result = op_stationarity_test(random_walk(), {"date": "date", "value": "value"}, "S")
        assert set(result.stats["adf"]["critical_values"]) >= {"1%", "5%", "10%"}
        assert set(result.stats["kpss"]["critical_values"]) >= {"1%", "5%", "10%"}

    def test_trend_regression_is_accepted(self):
        result = op_stationarity_test(
            trend_plus_season(), {"date": "date", "value": "value", "regression": "ct"}, "S"
        )
        assert result.stats["regression"] == "ct"

    def test_kpss_boundary_p_value_is_flagged_as_a_bound(self):
        # statsmodels interpolates KPSS p-values into [0.01, 0.10] and clamps
        # outside it; a clamped value is a bound, not a measurement.
        result = op_stationarity_test(random_walk(600), {"date": "date", "value": "value"}, "S")
        assert result.stats["kpss"]["p_value_is_bound"] is True
        assert result.stats["kpss"]["p_value"] == 0.01
        assert any("bound" in note for note in result.notes)


# ---------------------------------------------------------------------------
# autocorrelation
# ---------------------------------------------------------------------------


class TestAutocorrelation:
    def test_ar1_acf_decays_as_phi_to_the_k(self):
        result = op_autocorrelation(ar1_frame(), {"date": "date", "value": "value"}, "A")
        acf_by_lag = dict(zip(_column(result, "lag"), _column(result, "acf"), strict=True))
        for k in (1, 2, 3, 4):
            assert acf_by_lag[k] == pytest.approx(TRUE_PHI**k, abs=0.08)

    def test_ar1_pacf_cuts_off_after_lag_one(self):
        result = op_autocorrelation(ar1_frame(), {"date": "date", "value": "value"}, "A")
        rows = dict(zip(_column(result, "lag"), _column(result, "pacf"), strict=True))
        outside = dict(
            zip(_column(result, "lag"), _column(result, "pacf_outside_band"), strict=True)
        )
        assert rows[1] == pytest.approx(TRUE_PHI, abs=0.08)
        for k in (2, 3, 4, 5):
            assert outside[k] is False

    def test_lag_zero_is_not_reported(self):
        result = op_autocorrelation(ar1_frame(200), {"date": "date", "value": "value"}, "A")
        assert min(_column(result, "lag")) == 1

    def test_bartlett_bands_are_reported(self):
        result = op_autocorrelation(ar1_frame(200), {"date": "date", "value": "value"}, "A")
        lows = _column(result, "acf_ci95_low")
        highs = _column(result, "acf_ci95_high")
        assert all(low < high for low, high in zip(lows, highs, strict=True))
        assert result.stats["confidence_band"] == "Bartlett"

    def test_ljung_box_rejects_for_an_autocorrelated_series(self):
        result = op_autocorrelation(ar1_frame(), {"date": "date", "value": "value"}, "A")
        assert result.stats["ljung_box"]["p_value"] < 0.01
        assert result.stats["ljung_box"]["significant_at_0.05"] is True

    def test_ljung_box_does_not_reject_for_white_noise(self):
        result = op_autocorrelation(white_noise(300), {"date": "date", "value": "value"}, "A")
        assert result.stats["ljung_box"]["p_value"] > 0.05

    def test_requested_lags_are_capped_at_a_fraction_of_n(self):
        from app.services.analysis_timeseries import MAX_LAG_FRACTION

        n = 120
        result = op_autocorrelation(
            ar1_frame(n), {"date": "date", "value": "value", "lags": 100}, "A"
        )
        assert result.stats["lags_requested"] == 100
        assert result.stats["lags"] <= int(n * MAX_LAG_FRACTION)
        assert result.stats["lags_capped"] is True
        assert any("cap" in note.lower() for note in result.notes)

    def test_uncapped_request_is_honoured(self):
        result = op_autocorrelation(
            ar1_frame(400), {"date": "date", "value": "value", "lags": 12}, "A"
        )
        assert result.stats["lags"] == 12
        assert result.stats["lags_capped"] is False

    def test_stationarity_is_reported_as_an_assumption(self):
        result = op_autocorrelation(random_walk(), {"date": "date", "value": "value"}, "A")
        names = [check["name"] for check in result.stats["assumptions"]]
        assert any("stationar" in name.lower() for name in names)


# ---------------------------------------------------------------------------
# arima
# ---------------------------------------------------------------------------


class TestArima:
    def test_recovers_the_ar1_coefficient(self):
        frame = ar1_frame(300)
        values = frame["value"].to_numpy()
        # Independent estimate: the OLS regression of y[t] on y[t-1].
        phi_hat = float((values[1:] * values[:-1]).sum() / (values[:-1] ** 2).sum())

        result = op_arima(frame, {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0}, "M")
        coefficients = {row["term"]: row for row in result.stats["coefficients"]}
        ar1_coefficient = coefficients["ar.L1"]["coefficient"]
        assert ar1_coefficient > 0
        assert ar1_coefficient == pytest.approx(phi_hat, abs=0.1)
        assert ar1_coefficient == pytest.approx(TRUE_PHI, abs=0.15)

    def test_reports_information_criteria_and_standard_errors(self):
        result = op_arima(
            ar1_frame(200), {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0}, "M"
        )
        assert result.stats["aic"] is not None
        assert result.stats["bic"] is not None
        for row in result.stats["coefficients"]:
            assert row["std_error"] > 0
            assert row["ci95_low"] < row["ci95_high"]

    def test_forecast_interval_contains_the_true_continuation(self):
        horizon = 6
        full = ar1(300 + horizon, seed=41)
        dates = pd.date_range("2015-01-01", periods=300 + horizon, freq="D")
        history = _frame(dates[:300], value=full[:300])

        result = op_arima(
            history,
            {
                "date": "date",
                "value": "value",
                "p": 1,
                "d": 0,
                "q": 0,
                "forecast_periods": horizon,
            },
            "M",
        )
        rows = [row for row in result.rows if row[result.columns.index("kind")] == "forecast"]
        assert len(rows) == horizon
        low_index = result.columns.index("ci95_low")
        high_index = result.columns.index("ci95_high")
        for offset, row in enumerate(rows):
            truth = full[300 + offset]
            assert row[low_index] <= truth <= row[high_index]

    def test_forecast_interval_widens_with_the_horizon(self):
        result = op_arima(
            ar1_frame(300),
            {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0, "forecast_periods": 8},
            "M",
        )
        widths = [
            row[result.columns.index("ci95_high")] - row[result.columns.index("ci95_low")]
            for row in result.rows
            if row[result.columns.index("kind")] == "forecast"
        ]
        assert widths == sorted(widths)
        assert widths[-1] > widths[0]

    def test_forecast_rows_are_separated_from_observed_rows(self):
        result = op_arima(
            ar1_frame(120),
            {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0, "forecast_periods": 5},
            "M",
        )
        kinds = _column(result, "kind")
        assert set(kinds) == {"observed", "forecast"}
        # Observed rows carry no interval: they are measurements, not estimates.
        for row in result.rows:
            if row[result.columns.index("kind")] == "observed":
                assert row[result.columns.index("ci95_low")] is None

    def test_forecast_notes_state_that_intervals_assume_the_model(self):
        result = op_arima(
            ar1_frame(120),
            {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0, "forecast_periods": 5},
            "M",
        )
        joined = " ".join(result.notes).lower()
        assert "model" in joined
        assert "widen" in joined or "wider" in joined

    def test_forecast_is_absent_without_forecast_periods(self):
        result = op_arima(
            ar1_frame(120), {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0}, "M"
        )
        assert "kind" not in result.columns
        assert result.stats.get("forecast") is None

    def test_ljung_box_on_residuals_is_an_assumption(self):
        result = op_arima(
            ar1_frame(300), {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0}, "M"
        )
        names = [check["name"] for check in result.stats["assumptions"]]
        assert any("ljung" in name.lower() or "residual" in name.lower() for name in names)

    def test_refuses_an_order_the_series_cannot_support(self):
        short = ar1_frame(15)
        with pytest.raises(ExecutionError) as excinfo:
            op_arima(short, {"date": "date", "value": "value", "p": 6, "d": 1, "q": 6}, "M")
        message = str(excinfo.value).lower()
        assert "short" in message or "too few" in message

    def test_seasonal_order_without_a_period_is_refused_at_runtime(self):
        with pytest.raises(ExecutionError):
            op_arima(
                ar1_frame(120),
                {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0, "P": 1},
                "M",
            )


# ---------------------------------------------------------------------------
# granger_causality
# ---------------------------------------------------------------------------


class TestGrangerCausality:
    def test_detects_a_series_that_truly_leads(self):
        result = op_granger_causality(
            leading_pair(), {"date": "date", "value": "value", "cause": "cause", "max_lag": 4}, "G"
        )
        adjusted = _column(result, "p_value_adjusted")
        assert min(adjusted) < 0.01
        assert result.stats["any_lag_significant"] is True

    def test_does_not_detect_independent_series(self):
        result = op_granger_causality(
            independent_pair(),
            {"date": "date", "value": "value", "cause": "cause", "max_lag": 4},
            "G",
        )
        adjusted = _column(result, "p_value_adjusted")
        assert min(adjusted) > 0.05
        assert result.stats["any_lag_significant"] is False

    def test_adjusted_p_values_are_never_below_the_raw_ones(self):
        result = op_granger_causality(
            independent_pair(),
            {"date": "date", "value": "value", "cause": "cause", "max_lag": 4},
            "G",
        )
        raw = _column(result, "p_value")
        adjusted = _column(result, "p_value_adjusted")
        assert all(a >= r - 1e-12 for r, a in zip(raw, adjusted, strict=True))

    def test_every_result_says_precedence_is_not_causation(self):
        for frame in (leading_pair(), independent_pair()):
            result = op_granger_causality(
                frame, {"date": "date", "value": "value", "cause": "cause", "max_lag": 3}, "G"
            )
            joined = " ".join(result.notes).lower()
            assert "not causation" in joined or "not evidence of causation" in joined

    def test_adf_is_reported_for_both_series(self):
        result = op_granger_causality(
            leading_pair(), {"date": "date", "value": "value", "cause": "cause", "max_lag": 3}, "G"
        )
        names = " ".join(check["name"] for check in result.stats["assumptions"]).lower()
        assert "value" in names and "cause" in names

    def test_non_stationary_series_are_differenced_and_said_so(self):
        # Both series are random walks, so both are I(1). The innovations of
        # the cause drive the outcome's innovations one step later, so the
        # precedence is only visible once both are differenced.
        rng = np.random.default_rng(55)
        n = 250
        shocks = rng.normal(size=n)
        cause = np.cumsum(shocks)
        value = np.cumsum(0.9 * np.roll(shocks, 1) + rng.normal(scale=0.4, size=n))
        frame = _frame(pd.date_range("2019-01-01", periods=n, freq="D"), value=value, cause=cause)
        result = op_granger_causality(
            frame, {"date": "date", "value": "value", "cause": "cause", "max_lag": 3}, "G"
        )
        assert result.stats["differences_applied"] >= 1
        joined = " ".join(result.notes).lower()
        assert "difference" in joined

    def test_refuses_a_series_that_differencing_cannot_make_stationary(self):
        # Integrated three times: two differences still leave a random walk.
        rng = np.random.default_rng(23)
        n = 250

        def integrate(shocks: np.ndarray) -> np.ndarray:
            return np.cumsum(np.cumsum(np.cumsum(shocks)))

        frame = _frame(
            pd.date_range("2019-01-01", periods=n, freq="D"),
            value=integrate(rng.normal(size=n)),
            cause=integrate(rng.normal(size=n)),
        )
        with pytest.raises(ExecutionError) as excinfo:
            op_granger_causality(
                frame, {"date": "date", "value": "value", "cause": "cause", "max_lag": 2}, "G"
            )
        assert "stationar" in str(excinfo.value).lower()

    def test_reports_an_effect_size_and_interval(self):
        result = op_granger_causality(
            leading_pair(), {"date": "date", "value": "value", "cause": "cause", "max_lag": 3}, "G"
        )
        assert result.stats["effect_size"]["magnitude"]
        interval = result.stats["confidence_interval"]
        assert interval["low"] < interval["high"]


# ---------------------------------------------------------------------------
# Output contract shared by every tier-5 operation
# ---------------------------------------------------------------------------


def _all_results() -> list[Any]:
    return [
        op_decompose(trend_plus_season(), {"date": "date", "value": "value"}, "D"),
        op_stationarity_test(white_noise(), {"date": "date", "value": "value"}, "S"),
        op_autocorrelation(ar1_frame(300), {"date": "date", "value": "value"}, "A"),
        op_arima(
            ar1_frame(200),
            {"date": "date", "value": "value", "p": 1, "d": 0, "q": 0, "forecast_periods": 4},
            "M",
        ),
        op_granger_causality(
            leading_pair(), {"date": "date", "value": "value", "cause": "cause", "max_lag": 3}, "G"
        ),
    ]


class TestOutputContract:
    @pytest.fixture(scope="class")
    def results(self) -> list[Any]:
        return _all_results()

    def test_no_p_value_serializes_as_exactly_zero(self, results):
        for result in results:
            payload = json.loads(json.dumps(result.stats))
            values = _p_values(payload)
            assert values, f"{result.op} reported no p-value"
            for value in values:
                assert value != 0.0, f"{result.op} serialized a p-value as 0.0"
                assert math.isfinite(value)

    def test_every_result_reports_n_and_assumptions(self, results):
        for result in results:
            assert result.n > 0
            assert result.stats["assumptions"]
            assert all("passed" in check for check in result.stats["assumptions"])

    def test_every_result_describes_the_series_it_used(self, results):
        for result in results:
            series = result.stats["series"]
            assert series["frequency"] in SERIES_FREQS
            assert series["frequency_evidence"]
            assert series["periods"] > 0

    def test_every_result_is_json_serializable(self, results):
        for result in results:
            json.dumps({"table": result.to_table(), "stats": result.stats, "notes": result.notes})

    def test_every_result_carries_an_effect_size_and_interval(self, results):
        for result in results:
            assert result.stats["effect_size"]["name"]
            assert result.stats["confidence_interval"]["level"] == 0.95

    def test_the_first_plottable_column_is_numeric(self, results):
        # build_chart falls back to column 1 when no per-operation default is
        # registered, so column 1 must never be a label.
        for result in results:
            assert result.rows
            assert isinstance(result.rows[0][1], (int, float))
