"""Tier 5: what a series does over time, and what it will plausibly do next.

Where tier 3 asks whether two groups differ, this module asks whether a series
trends, repeats, remembers its own past, and whether one series precedes
another. All five operations rest on the same precondition — observations at a
constant interval — which uploaded data essentially never satisfies. That
preparation, and the honest reporting of what it had to invent, lives in
:mod:`app.services.analysis_timeseries_prep` and is the first thing every
operation here does.

Two outputs in this tier are more abusable than anything else the product
produces, and both are handled deliberately rather than incidentally.

A **forecast** is a claim about the future stated in the same typeface as a
measurement. Every forecast row is therefore marked as a forecast, carries a
prediction interval in the same row, and arrives with notes stating that the
interval assumes the fitted model is correct and widens with the horizon. A
point forecast without its interval is not shipped from here at all.

**Granger causality** is named after a man who was careful to call it
predictive precedence, and the name has been misread ever since. Every result
from that operation carries a note saying so, whatever the p-value.

The third hazard is quieter: a unit-root test, an ACF or an ARIMA fit over a
series whose gaps were forward-filled reports the smoothness of the filling as
a property of the world. Interpolated periods are counted, named in the notes,
and fail the regular-spacing assumption, which the narrator is required to
surface.
"""

from __future__ import annotations

import logging
import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tools.sm_exceptions import InfeasibleTestError, InterpolationWarning
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.seasonal import STL, seasonal_decompose
from statsmodels.tsa.stattools import acf, adfuller, grangercausalitytests, kpss, pacf

from app.services.analysis_prep import assumptions, exclusion_note, significant
from app.services.analysis_registry import OperationDef, Param
from app.services.analysis_result import ExecutionError, OperationResult, frame_to_result
from app.services.analysis_stats import (
    ALPHA,
    CONFIDENCE_LEVEL,
    Assumption,
    benjamini_hochberg,
    effect_size,
    interval,
)
from app.services.analysis_timeseries_prep import (
    SERIES_FREQS,
    PreparedSeries,
    prepare_series,
    seasonal_period_for,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# MacKinnon's ADF p-value is a polynomial approximation that underflows to
# exactly 0.0 for strongly mean-reverting series. Zero is a claim no test can
# support, so such a value is reported at this floor and flagged as a bound.
MACKINNON_P_FLOOR = 1e-10

# A decomposition needs whole cycles to separate a repeating pattern from a
# trend. STL estimates a seasonal component that evolves, which takes more
# history than the classical fixed-seasonal average; below that it is the
# classical method or nothing.
MIN_DECOMPOSE_CYCLES = 2
STL_MIN_CYCLES = 3

# STL's seasonal smoother, in periods. The default of 7 is short enough that
# STL fits noise into the seasonal component: on pure white noise the standard
# seasonal-strength measure comes out near 0.4 rather than near 0. A
# locally-constant smoother spanning two cycles brings that to below 0.1 while
# leaving a genuine seasonal pattern untouched.
STL_SEASONAL_CYCLES = 2
STL_SEASONAL_DEGREE = 0

# Autocorrelations past a quarter of the series are estimated from so few
# overlapping pairs that they are noise; this is the conventional n/4 rule.
MAX_LAG_FRACTION = 0.25
# And an absolute ceiling, so a long series does not return a 5,000-row table.
MAX_LAGS = 60

# Differencing beyond this is almost always a sign the series needs a
# transformation (a log, say) rather than another difference.
MAX_DIFFERENCES = 2

# Observations an ARIMA fit needs beyond its own parameter count before the
# standard errors mean anything.
MIN_RESIDUAL_PERIODS = 10

# How much observed history a forecast table carries for context, as a
# multiple of the horizon — enough to see where the forecast departs from,
# bounded so the forecast itself is never truncated out of the table.
FORECAST_CONTEXT_MULTIPLE = 3
MAX_FORECAST_CONTEXT = 60

_PERCENTILE_KEYS = ("1%", "5%", "10%")


def _bounded_p(value: float, floor: float = MACKINNON_P_FLOOR) -> tuple[float, bool]:
    """A p-value that is never exactly zero, and a flag saying when it is a bound."""
    as_float = float(value)
    if not math.isfinite(as_float) or as_float <= floor:
        return floor, True
    return as_float, False


def _strength(residual: np.ndarray, component: np.ndarray) -> float:
    """Wang-Smith-Hyndman strength of a decomposition component, on [0, 1].

    ``1 - Var(remainder) / Var(remainder + component)``: how much of what the
    component and the noise jointly explain is the component rather than the
    noise. Clipped, because the ratio can exceed one when the component and the
    remainder are negatively correlated, which is an artefact of the estimator
    rather than negative strength.
    """
    combined = np.nanvar(residual + component, ddof=1)
    if not math.isfinite(combined) or combined <= 0:
        return math.nan
    return float(np.clip(1.0 - np.nanvar(residual, ddof=1) / combined, 0.0, 1.0))


def _series_payload(prepared: PreparedSeries, **extra: Any) -> dict[str, Any]:
    return {"series": prepared.stats(), **extra}


def _slope_with_interval(values: np.ndarray) -> tuple[float, float, float]:
    """OLS slope per period of *values* against its own index, with a 95% interval."""
    finite = np.isfinite(values)
    y = values[finite]
    x = np.arange(values.size, dtype=float)[finite]
    if y.size < 3:
        return math.nan, math.nan, math.nan
    fit = stats.linregress(x, y)
    critical = float(stats.t.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2, y.size - 2))
    margin = critical * float(fit.stderr)
    return float(fit.slope), float(fit.slope) - margin, float(fit.slope) + margin


def _ljung_box(residual: np.ndarray, lags: int, model_df: int = 0) -> tuple[float, float, int]:
    """Joint test that the first *lags* autocorrelations are all zero."""
    clean = residual[np.isfinite(residual)]
    dof = max(1, lags - model_df)
    usable = min(lags, max(1, clean.size // 5))
    if clean.size < 8 or usable <= model_df:
        return math.nan, math.nan, dof
    table = acorr_ljungbox(clean, lags=[usable], model_df=model_df, return_df=True)
    return (
        float(table["lb_stat"].iloc[0]),
        float(table["lb_pvalue"].iloc[0]),
        max(1, usable - model_df),
    )


# ---------------------------------------------------------------------------
# decompose
# ---------------------------------------------------------------------------


def _stl_window(period: int) -> int:
    """An odd seasonal smoother spanning :data:`STL_SEASONAL_CYCLES` cycles."""
    window = STL_SEASONAL_CYCLES * period + 1
    return max(7, window if window % 2 else window + 1)


def _decompose_components(
    series: pd.Series, period: int
) -> tuple[str, np.ndarray, np.ndarray, np.ndarray]:
    """Split *series* into trend, seasonal and remainder by the best method it supports."""
    n = series.size
    if n < MIN_DECOMPOSE_CYCLES * period:
        raise ExecutionError(
            f"decompose: {n} period(s) is fewer than the {MIN_DECOMPOSE_CYCLES} full cycles "
            f"of {period} that a seasonal decomposition needs. Give a shorter "
            f"seasonal_period, or resample to a coarser frequency."
        )

    if n >= STL_MIN_CYCLES * period:
        fitted = STL(
            series,
            period=period,
            seasonal=_stl_window(period),
            seasonal_deg=STL_SEASONAL_DEGREE,
        ).fit()
        method = f"STL (LOESS, seasonal window {_stl_window(period)})"
        return method, fitted.trend.to_numpy(), fitted.seasonal.to_numpy(), fitted.resid.to_numpy()

    fitted = seasonal_decompose(series, model="additive", period=period)
    method = (
        f"classical additive decomposition (a centred moving average; the series carries "
        f"{n / period:.1f} cycles, too few for STL)"
    )
    return (
        method,
        fitted.trend.to_numpy(),
        fitted.seasonal.to_numpy(),
        fitted.resid.to_numpy(),
    )


def op_decompose(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """Split a series into trend, repeating pattern, and what is left over."""
    prepared = prepare_series(df, params, op="decompose")
    column = params["value"]
    period = seasonal_period_for(params, prepared.freq, "decompose")
    series = prepared.frame[column]

    method, trend, seasonal, residual = _decompose_components(series, period)
    trend_strength = _strength(residual, trend)
    seasonal_strength = _strength(residual, seasonal)
    slope, slope_low, slope_high = _slope_with_interval(trend)
    peak_to_trough = float(np.nanmax(seasonal) - np.nanmin(seasonal))
    lb_statistic, lb_p, lb_dof = _ljung_box(residual, min(2 * period, MAX_LAGS))

    frame = pd.DataFrame(
        {
            "date": prepared.index,
            "observed": series.to_numpy(),
            "trend": trend,
            "seasonal": seasonal,
            "residual": residual,
        }
    )
    payload = _series_payload(
        prepared,
        method=method,
        seasonal_period=period,
        trend_strength=trend_strength,
        seasonal_strength=seasonal_strength,
        trend_slope_per_period=slope,
        seasonal_amplitude=peak_to_trough / 2,
        seasonal_peak_to_trough=peak_to_trough,
        residual_sd=float(np.nanstd(residual, ddof=1)),
        effect_size=effect_size(
            "seasonal strength",
            seasonal_strength,
            "variance_explained",
            trend_strength=trend_strength,
            definition="1 - Var(remainder) / Var(remainder + component), on [0, 1]",
        ),
        confidence_interval=interval(
            slope_low,
            slope_high,
            of=f"the average change in {column} per {prepared.freq} period",
            caveat=(
                "fitted to the smoothed trend component, so it understates uncertainty "
                "about the underlying series"
            ),
        ),
        assumptions=assumptions(
            prepared.assumption(),
            Assumption(
                "Additive structure",
                None,
                "the components are assumed to add; a series whose seasonal swings grow "
                "with its level needs a multiplicative decomposition, which shows up here "
                "as seasonal structure left in the remainder",
            ),
            _residual_whiteness(lb_statistic, lb_p, lb_dof, "the remainder"),
        ),
    )
    notes = prepared.notes() + exclusion_note(prepared.n_excluded)
    notes.append(
        f"Trend and seasonal strength are on [0, 1]: {trend_strength:.2f} and "
        f"{seasonal_strength:.2f} here. They describe this decomposition, not a test."
    )
    return frame_to_result(
        frame,
        op="decompose",
        label=label,
        n=prepared.n_periods,
        n_excluded=prepared.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


def _residual_whiteness(statistic: float, p_value: float, dof: int, subject: str) -> Assumption:
    """Whether a Ljung-Box test finds structure left in *subject*."""
    name = f"No autocorrelation left in {subject}"
    if not math.isfinite(p_value):
        return Assumption(name, None, "too few observations for a Ljung-Box test")
    bounded, _ = _bounded_p(p_value, ALPHA / 1e6)
    passed = bool(bounded >= ALPHA)
    detail = f"Ljung-Box Q({dof}) = {statistic:.4g}, p = {bounded:.4g}; " + (
        "no autocorrelation is detectable"
        if passed
        else "structure remains, so the model has not captured everything in the series"
    )
    return Assumption(name, passed, detail, statistic, bounded)


# ---------------------------------------------------------------------------
# stationarity_test
# ---------------------------------------------------------------------------

# ADF's null is a unit root; KPSS's null is stationarity. They are run together
# because their disagreement is informative: two tests of opposite nulls
# distinguish "stationary", "unit root", "stationary around a deterministic
# trend" and "neither test is decisive" — a distinction a single test cannot
# make, and the one that decides whether to difference or to detrend.
JOINT_VERDICTS: dict[tuple[bool, bool], tuple[str, str]] = {
    (True, False): (
        "stationary",
        "ADF rejects a unit root and KPSS does not reject stationarity: both tests agree "
        "the series is stationary, so it can be modelled as it stands.",
    ),
    (False, True): (
        "unit_root",
        "ADF cannot reject a unit root and KPSS rejects stationarity: both tests agree the "
        "series is non-stationary. Difference it before fitting or correlating anything.",
    ),
    (True, True): (
        "trend_stationary",
        "ADF rejects a unit root but KPSS also rejects stationarity: the series is "
        "stationary around a deterministic trend rather than a constant. Detrend it "
        "rather than differencing it.",
    ),
    (False, False): (
        "inconclusive",
        "Neither test is decisive — ADF cannot reject a unit root and KPSS cannot reject "
        "stationarity. This usually means the series is too short or too weakly "
        "autocorrelated for either test to resolve; treat the question as open.",
    ),
}


def _adf(values: np.ndarray, regression: str) -> dict[str, Any]:
    result = adfuller(values, regression=regression, autolag="AIC", result_object=True)
    p_value, is_bound = _bounded_p(float(result.pvalue))
    return {
        "test": "Augmented Dickey-Fuller (null: a unit root is present)",
        "statistic": float(result.statistic),
        "p_value": p_value,
        "p_value_is_bound": is_bound,
        "lags_used": int(result.lags),
        "n_observations": int(result.nobs),
        "critical_values": {key: float(v) for key, v in result.critical_values.items()},
        "rejects_unit_root": bool(p_value < ALPHA),
    }


def _kpss(values: np.ndarray, regression: str) -> dict[str, Any]:
    # statsmodels interpolates the KPSS p-value from a small published table
    # and warns when the statistic falls outside it. Outside the table the
    # returned value is the table's edge, which is a bound rather than a
    # measurement — and saying so is the difference between "p = 0.01" and
    # "p is at most 0.01".
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = kpss(values, regression=regression, nlags="auto", result_object=True)
    is_bound = any(issubclass(entry.category, InterpolationWarning) for entry in caught)
    p_value = float(result.pvalue)
    return {
        "test": "KPSS (null: the series is stationary)",
        "statistic": float(result.statistic),
        "p_value": p_value,
        "p_value_is_bound": is_bound,
        "lags_used": int(result.lags),
        "critical_values": {
            key: float(value)
            for key, value in result.critical_values.items()
            if key in _PERCENTILE_KEYS
        },
        "rejects_stationarity": bool(p_value < ALPHA),
    }


def _differences_to_stationarity(values: np.ndarray, regression: str) -> int:
    """How many differences it takes before ADF rejects a unit root."""
    working = values
    for order in range(MAX_DIFFERENCES + 1):
        if working.size < MIN_RESIDUAL_PERIODS:
            return order
        try:
            result = adfuller(working, regression=regression, autolag="AIC", result_object=True)
        except (ValueError, np.linalg.LinAlgError) as exc:  # degenerate after differencing
            logger.info("stationarity: ADF failed at difference %d (%s)", order, exc)
            return order
        if float(result.pvalue) < ALPHA:
            return order
        working = np.diff(working)
    return MAX_DIFFERENCES + 1


def _lag_one_autocorrelation(values: np.ndarray) -> tuple[float, float, float]:
    """Lag-1 autocorrelation with a Bartlett interval — how persistent the series is."""
    n = values.size
    if n < 3:
        return math.nan, math.nan, math.nan
    rho = float(acf(values, nlags=1, result_object=True).acf[1])
    margin = float(stats.norm.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2)) / math.sqrt(n)
    return rho, rho - margin, rho + margin


def op_stationarity_test(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """ADF and KPSS together, with the joint verdict their disagreement implies."""
    prepared = prepare_series(df, params, op="stationarity_test")
    column = params["value"]
    regression = str(params.get("regression", "c"))
    values = prepared.series(column)

    adf_result = _adf(values, regression)
    kpss_result = _kpss(values, regression)
    code, wording = JOINT_VERDICTS[
        (adf_result["rejects_unit_root"], kpss_result["rejects_stationarity"])
    ]
    differences = _differences_to_stationarity(values, regression)
    rho, rho_low, rho_high = _lag_one_autocorrelation(values)

    frame = pd.DataFrame(
        [
            {
                "test": entry["test"].split(" (")[0],
                "statistic": entry["statistic"],
                "p_value": entry["p_value"],
                "lags_used": entry["lags_used"],
                "critical_1pct": entry["critical_values"].get("1%"),
                "critical_5pct": entry["critical_values"].get("5%"),
                "critical_10pct": entry["critical_values"].get("10%"),
                "null_hypothesis_rejected": rejected,
            }
            for entry, rejected in (
                (adf_result, adf_result["rejects_unit_root"]),
                (kpss_result, kpss_result["rejects_stationarity"]),
            )
        ]
    )
    payload = _series_payload(
        prepared,
        regression=regression,
        regression_meaning=(
            "constant only" if regression == "c" else "constant and deterministic trend"
        ),
        adf=adf_result,
        kpss=kpss_result,
        verdict=wording,
        verdict_code=code,
        differences_suggested=min(differences, MAX_DIFFERENCES + 1),
        effect_size=effect_size(
            "lag-1 autocorrelation",
            rho,
            "correlation",
            reading="near 1 means shocks persist; near 0 means the series forgets them",
        ),
        confidence_interval=interval(
            rho_low, rho_high, of="the lag-1 autocorrelation", band="Bartlett"
        ),
        assumptions=assumptions(
            prepared.assumption(),
            Assumption(
                "Opposite nulls",
                None,
                "ADF tests for a unit root and KPSS tests for stationarity, so 'passing' "
                "means the opposite thing in each; the joint verdict reads them together "
                "rather than trusting either alone",
            ),
        ),
    )
    notes = prepared.notes() + exclusion_note(prepared.n_excluded) + [wording]
    if differences > MAX_DIFFERENCES:
        notes.append(
            f"Still non-stationary after {MAX_DIFFERENCES} difference(s); a transformation "
            f"(a log, for a series whose swings grow with its level) is more likely to help "
            f"than a third difference."
        )
    elif differences:
        notes.append(f"{differences} difference(s) would be enough to reach stationarity by ADF.")
    if kpss_result["p_value_is_bound"]:
        notes.append(
            f"The KPSS p-value is at the edge of the published table, so it is reported as "
            f"a bound ({kpss_result['p_value']:.2f}) rather than an exact value."
        )
    return frame_to_result(
        frame,
        op="stationarity_test",
        label=label,
        n=prepared.n_periods,
        n_excluded=prepared.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# autocorrelation
# ---------------------------------------------------------------------------


def _resolve_lags(requested: Any, n: int) -> tuple[int, int | None, bool]:
    """The number of lags to report, and whether the request had to be cut down."""
    ceiling = max(1, min(int(n * MAX_LAG_FRACTION), MAX_LAGS))
    if requested is None:
        # Box-Jenkins' rule of thumb, held under the same ceiling.
        default = max(1, int(round(10 * math.log10(max(n, 10)))))
        return min(default, ceiling), None, False
    asked = int(requested)
    if asked < 1:
        raise ExecutionError(f"autocorrelation: lags must be at least 1, got {asked}")
    return min(asked, ceiling), asked, asked > ceiling


def op_autocorrelation(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """ACF and PACF with Bartlett bands, plus a Ljung-Box test over all the lags."""
    prepared = prepare_series(df, params, op="autocorrelation")
    column = params["value"]
    values = prepared.series(column)
    lags, requested, capped = _resolve_lags(params.get("lags"), values.size)

    acf_result = acf(
        values,
        nlags=lags,
        alpha=1 - CONFIDENCE_LEVEL,
        bartlett_confint=True,
        result_object=True,
    )
    pacf_result = pacf(values, nlags=lags, alpha=1 - CONFIDENCE_LEVEL, result_object=True)
    acf_values, acf_bounds = acf_result.acf, acf_result.confint
    pacf_values, pacf_bounds = pacf_result.pacf, pacf_result.confint

    rows = [
        {
            "lag": lag,
            "acf": float(acf_values[lag]),
            "acf_ci95_low": float(acf_bounds[lag][0]),
            "acf_ci95_high": float(acf_bounds[lag][1]),
            "acf_outside_band": bool(acf_bounds[lag][0] > 0 or acf_bounds[lag][1] < 0),
            "pacf": float(pacf_values[lag]),
            "pacf_ci95_low": float(pacf_bounds[lag][0]),
            "pacf_ci95_high": float(pacf_bounds[lag][1]),
            "pacf_outside_band": bool(pacf_bounds[lag][0] > 0 or pacf_bounds[lag][1] < 0),
        }
        for lag in range(1, lags + 1)
    ]

    lb_statistic, lb_p, lb_dof = _ljung_box(values, lags)
    lb_bounded, lb_is_bound = _bounded_p(lb_p, ALPHA / 1e6)
    adf_result = _adf(values, "c")
    rho_low = float(acf_bounds[1][0])
    rho_high = float(acf_bounds[1][1])

    payload = _series_payload(
        prepared,
        lags=lags,
        lags_requested=requested,
        lags_capped=capped,
        confidence_band="Bartlett",
        ljung_box={
            "test": f"Ljung-Box, all {lb_dof} lag(s) jointly",
            "statistic": lb_statistic,
            "dof": lb_dof,
            "p_value": lb_bounded,
            "p_value_is_bound": lb_is_bound,
            "significant_at_0.05": significant(lb_bounded),
        },
        effect_size=effect_size(
            "lag-1 autocorrelation",
            float(acf_values[1]),
            "correlation",
            reading="how much of this period is predictable from the last one",
        ),
        confidence_interval=interval(
            rho_low, rho_high, of="the lag-1 autocorrelation", band="Bartlett"
        ),
        assumptions=assumptions(
            prepared.assumption(),
            Assumption(
                "Stationarity",
                adf_result["rejects_unit_root"],
                f"ADF p = {adf_result['p_value']:.4g}; "
                + (
                    "the series is stationary, so these autocorrelations describe it"
                    if adf_result["rejects_unit_root"]
                    else "a unit root cannot be ruled out, and the ACF of a non-stationary "
                    "series decays slowly whatever its underlying structure — difference "
                    "it before reading these values"
                ),
                adf_result["statistic"],
                adf_result["p_value"],
            ),
        ),
    )
    notes = prepared.notes() + exclusion_note(prepared.n_excluded)
    notes.append(
        f"Bands are Bartlett {CONFIDENCE_LEVEL:.0%} intervals; a lag whose band excludes "
        f"zero is flagged in acf_outside_band. With {lags} lags, roughly "
        f"{max(1, round(lags * ALPHA))} will fall outside by chance alone."
    )
    if capped:
        notes.append(
            f"Requested {requested} lags, capped at {lags} — "
            f"{MAX_LAG_FRACTION:.0%} of the {values.size}-period series, beyond which the "
            f"estimates rest on too few overlapping pairs to mean anything."
        )
    return frame_to_result(
        pd.DataFrame(rows),
        op="autocorrelation",
        label=label,
        n=prepared.n_periods,
        n_excluded=prepared.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# arima
# ---------------------------------------------------------------------------


def _orders(params: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int, int]]:
    order = (int(params["p"]), int(params["d"]), int(params["q"]))
    seasonal_terms = {key: int(params[key]) for key in ("P", "D", "Q") if key in params}
    if not seasonal_terms:
        return order, (0, 0, 0, 0)
    period = params.get("seasonal_period")
    if period is None:
        raise ExecutionError(
            "arima: a seasonal order (P, D or Q) needs seasonal_period — the length of the "
            "cycle in periods (12 for monthly data with a yearly cycle, 4 for quarterly)"
        )
    return order, (
        seasonal_terms.get("P", 0),
        seasonal_terms.get("D", 0),
        seasonal_terms.get("Q", 0),
        int(period),
    )


def _require_length(n: int, order: tuple[int, ...], seasonal: tuple[int, ...]) -> None:
    p, d, q = order
    seasonal_p, seasonal_d, seasonal_q, period = seasonal
    needed = p + q + d + (seasonal_p + seasonal_q + seasonal_d) * period + MIN_RESIDUAL_PERIODS
    if n < needed:
        raise ExecutionError(
            f"arima: the series is too short for order ({p},{d},{q})"
            + (f" x ({seasonal_p},{seasonal_d},{seasonal_q},{period})" if period else "")
            + f" — {n} period(s) against the {needed} that order needs before its standard "
            f"errors mean anything. Use a lower order, or a finer frequency."
        )


def _fit_arima(series: pd.Series, order: tuple[int, int, int], seasonal: tuple[int, ...]) -> Any:
    with warnings.catch_warnings():
        # Convergence and non-invertibility warnings are reported through the
        # coefficient table and the residual test instead of being raised.
        warnings.simplefilter("ignore")
        try:
            return ARIMA(series, order=order, seasonal_order=seasonal).fit()
        except (ValueError, np.linalg.LinAlgError) as exc:
            raise ExecutionError(f"arima: the model could not be fitted ({exc})") from exc


def _coefficient_rows(fitted: Any) -> list[dict[str, Any]]:
    bounds = fitted.conf_int(alpha=1 - CONFIDENCE_LEVEL)
    rows = []
    for term in fitted.params.index:
        p_value, is_bound = _bounded_p(float(fitted.pvalues[term]), ALPHA / 1e8)
        rows.append(
            {
                "term": str(term),
                "coefficient": float(fitted.params[term]),
                "std_error": float(fitted.bse[term]),
                "z": float(fitted.params[term] / fitted.bse[term])
                if float(fitted.bse[term]) > 0
                else math.nan,
                "p_value": p_value,
                "p_value_is_bound": is_bound,
                "ci95_low": float(bounds.loc[term].iloc[0]),
                "ci95_high": float(bounds.loc[term].iloc[1]),
            }
        )
    return rows


def _forecast_frame(
    fitted: Any, observed: pd.Series, horizon: int
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Observed history then forecast rows, each marked and each carrying its interval."""
    summary = fitted.get_forecast(steps=horizon).summary_frame(alpha=1 - CONFIDENCE_LEVEL)
    context = min(FORECAST_CONTEXT_MULTIPLE * horizon, MAX_FORECAST_CONTEXT, observed.size)
    tail = observed.iloc[-context:]

    history = pd.DataFrame(
        {
            "date": tail.index,
            "value": tail.to_numpy(dtype=float),
            "ci95_low": np.nan,
            "ci95_high": np.nan,
            "kind": "observed",
        }
    )
    forecast = pd.DataFrame(
        {
            "date": summary.index,
            "value": summary["mean"].to_numpy(dtype=float),
            "ci95_low": summary["mean_ci_lower"].to_numpy(dtype=float),
            "ci95_high": summary["mean_ci_upper"].to_numpy(dtype=float),
            "kind": "forecast",
        }
    )
    rows = [
        {
            "date": stamp.isoformat(),
            "forecast": float(row["mean"]),
            "std_error": float(row["mean_se"]),
            "ci95_low": float(row["mean_ci_lower"]),
            "ci95_high": float(row["mean_ci_upper"]),
            "horizon": step,
        }
        for step, (stamp, row) in enumerate(summary.iterrows(), start=1)
    ]
    return pd.concat([history, forecast], ignore_index=True), rows


def op_arima(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """Fit an ARIMA (or SARIMA) model, and optionally forecast from it."""
    prepared = prepare_series(df, params, op="arima")
    column = params["value"]
    order, seasonal = _orders(params)
    _require_length(prepared.n_periods, order, seasonal)

    observed = prepared.frame[column]
    fitted = _fit_arima(observed, order, seasonal)
    coefficients = _coefficient_rows(fitted)
    residual = np.asarray(fitted.resid, dtype=float)
    model_df = order[0] + order[2] + (seasonal[0] + seasonal[2]) * (seasonal[3] or 1)
    lb_statistic, lb_p, lb_dof = _ljung_box(
        residual, min(2 * (model_df + 1) + 8, MAX_LAGS), model_df=model_df
    )
    explained = _strength(residual, observed.to_numpy(dtype=float) - residual)

    horizon = params.get("forecast_periods")
    notes = prepared.notes() + exclusion_note(prepared.n_excluded)
    forecast_payload: dict[str, Any] | None = None

    if horizon is None:
        frame = pd.DataFrame(coefficients).drop(columns=["p_value_is_bound"])
    else:
        steps = int(horizon)
        if steps < 1:
            raise ExecutionError(f"arima: forecast_periods must be at least 1, got {steps}")
        frame, forecast_rows = _forecast_frame(fitted, observed, steps)
        forecast_payload = {
            "periods": steps,
            "level": CONFIDENCE_LEVEL,
            "rows": forecast_rows,
            "interval_meaning": (
                "a prediction interval for a future observation, not a confidence interval "
                "for an average"
            ),
        }
        notes += _forecast_notes(steps, prepared.freq, lb_p)

    payload = _series_payload(
        prepared,
        model=f"ARIMA{order}" + (f" x {seasonal}" if any(seasonal[:3]) else "") + f" on {column}",
        order={"p": order[0], "d": order[1], "q": order[2]},
        seasonal_order={
            "P": seasonal[0],
            "D": seasonal[1],
            "Q": seasonal[2],
            "seasonal_period": seasonal[3],
        }
        if any(seasonal[:3])
        else None,
        aic=float(fitted.aic),
        bic=float(fitted.bic),
        hqic=float(fitted.hqic),
        log_likelihood=float(fitted.llf),
        sigma2=float(getattr(fitted, "mse", math.nan)),
        coefficients=coefficients,
        forecast=forecast_payload,
        effect_size=effect_size(
            "in-sample variance explained",
            explained,
            "variance_explained",
            definition="1 - Var(residual) / Var(fitted + residual); in-sample fit, not "
            "out-of-sample accuracy",
        ),
        confidence_interval=_headline_interval(coefficients, order),
        assumptions=assumptions(
            prepared.assumption(),
            _residual_whiteness(lb_statistic, lb_p, lb_dof, "the model residuals"),
            Assumption(
                "Model correctness",
                None,
                "every number here — the coefficients, the information criteria, and any "
                "prediction interval — is conditional on this order being the right one; "
                "none of them account for the risk that it is not",
            ),
        ),
    )
    return frame_to_result(
        frame,
        op="arima",
        label=label,
        n=prepared.n_periods,
        n_excluded=prepared.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


def _headline_interval(coefficients: list[dict[str, Any]], order: tuple[int, int, int]) -> Any:
    """The interval on the leading model term, so the result has one to show."""
    preferred = "ar.L1" if order[0] else ("ma.L1" if order[2] else "const")
    chosen = next(
        (row for row in coefficients if row["term"] == preferred),
        coefficients[0] if coefficients else None,
    )
    if chosen is None:  # pragma: no cover - a fitted model always has parameters
        return interval(math.nan, math.nan, of="no estimated coefficient")
    return interval(chosen["ci95_low"], chosen["ci95_high"], of=f"the {chosen['term']} coefficient")


def _forecast_notes(steps: int, freq: str, residual_p: float) -> list[str]:
    """The caveats a forecast must never ship without."""
    notes = [
        f"The last {steps} row(s) are forecasts, marked 'forecast' in the kind column; "
        f"every earlier row is an observation. Forecast rows carry a "
        f"{CONFIDENCE_LEVEL:.0%} prediction interval and observed rows carry none, "
        f"because observations were measured rather than estimated.",
        f"The interval is the range the next value is expected to fall in {CONFIDENCE_LEVEL:.0%} "
        f"of the time IF this model is the right one. It widens with each step ahead, and it "
        f"does not cover the risk that the model is wrong, that the pattern breaks, or that "
        f"something happens over the next {steps} {freq} period(s) that never happened in the "
        f"history the model was fitted to. Report the interval, never the point alone.",
    ]
    if math.isfinite(residual_p) and residual_p < ALPHA:
        notes.append(
            "The residuals still show autocorrelation, so the model has not captured "
            "everything in the series and the interval is likely too narrow."
        )
    return notes


# ---------------------------------------------------------------------------
# granger_causality
# ---------------------------------------------------------------------------

GRANGER_DISCLAIMER = (
    "Granger causality is predictive precedence, not causation: it says past values of the "
    "cause series improve the forecast of the outcome, which is equally consistent with a "
    "common driver, a reporting lag, or coincidence. It is not evidence of causation."
)


def _difference_to_stationarity(
    frame: pd.DataFrame, columns: tuple[str, str], regression: str = "c"
) -> tuple[pd.DataFrame, int, dict[str, dict[str, Any]]]:
    """Difference both series together until ADF rejects a unit root in each.

    Both series are differenced the same number of times whether or not both
    needed it, because a Granger test compares lags across the two and mixing
    levels with differences would compare different quantities.
    """
    working = frame
    for applied in range(MAX_DIFFERENCES + 1):
        results = {name: _adf(working[name].to_numpy(dtype=float), regression) for name in columns}
        if all(entry["rejects_unit_root"] for entry in results.values()):
            return working, applied, results
        working = working.diff().dropna()
        if len(working) < MIN_RESIDUAL_PERIODS:
            break
    failing = [name for name, entry in results.items() if not entry["rejects_unit_root"]]
    raise ExecutionError(
        f"granger_causality: {failing} remain non-stationary after {MAX_DIFFERENCES} "
        f"difference(s) (ADF cannot reject a unit root at {ALPHA:g}). A Granger test on "
        f"non-stationary series produces spurious significance. Run stationarity_test to "
        f"see what the series is doing; a series whose swings grow with its level usually "
        f"needs a log rather than another difference."
    )


def _summed_cause_interval(
    outcome: np.ndarray, cause: np.ndarray, lag: int
) -> tuple[float, float, float]:
    """The total coefficient on the lagged cause, with a 95% interval.

    The F-test says whether the lagged cause matters; this says by how much and
    in which direction, which the F-statistic alone cannot.
    """
    rows = outcome.size - lag
    if rows <= 2 * lag + 2:
        return math.nan, math.nan, math.nan
    design = np.column_stack(
        [np.ones(rows)]
        + [outcome[lag - step : outcome.size - step] for step in range(1, lag + 1)]
        + [cause[lag - step : cause.size - step] for step in range(1, lag + 1)]
    )
    fitted = OLS(outcome[lag:], design).fit()
    contrast = np.zeros(design.shape[1])
    contrast[1 + lag :] = 1.0
    estimate = float(contrast @ fitted.params)
    variance = float(contrast @ fitted.cov_params() @ contrast)
    if not math.isfinite(variance) or variance <= 0:
        return estimate, math.nan, math.nan
    margin = float(stats.t.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2, fitted.df_resid)) * math.sqrt(
        variance
    )
    return estimate, estimate - margin, estimate + margin


def _partial_eta_squared(f_statistic: float, df_num: float, df_denom: float) -> float:
    """Share of the outcome's remaining variance the lagged cause accounts for."""
    numerator = f_statistic * df_num
    if not math.isfinite(numerator) or numerator + df_denom <= 0:
        return math.nan
    return float(numerator / (numerator + df_denom))


def op_granger_causality(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """Whether past values of one series improve the forecast of another."""
    outcome_name, cause_name = params["value"], params["cause"]
    if outcome_name == cause_name:
        raise ExecutionError("granger_causality: 'cause' and 'value' must be different columns")

    prepared = prepare_series(df, params, op="granger_causality", values=(outcome_name, cause_name))
    frame, differences, adf_results = _difference_to_stationarity(
        prepared.frame, (outcome_name, cause_name)
    )
    max_lag = _resolve_max_lag(params.get("max_lag"), len(frame))

    outcome = frame[outcome_name].to_numpy(dtype=float)
    cause = frame[cause_name].to_numpy(dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            tests = grangercausalitytests(np.column_stack([outcome, cause]), maxlag=max_lag)
        except InfeasibleTestError as exc:
            raise ExecutionError(
                f"granger_causality: the test cannot be computed on these series ({exc}). "
                f"That happens when one series is a deterministic function of the other."
            ) from exc
        except (ValueError, np.linalg.LinAlgError) as exc:
            raise ExecutionError(f"granger_causality: the test could not be run ({exc})") from exc

    rows = _granger_rows(tests)
    adjusted = benjamini_hochberg([row["p_value"] for row in rows])
    for row, value in zip(rows, adjusted, strict=True):
        row["p_value_adjusted"] = value
        row["significant_at_0.05"] = significant(float(value)) if value is not None else None

    best = min(rows, key=lambda row: row["p_value_adjusted"])
    eta = _partial_eta_squared(best["f_statistic"], best["df_num"], best["df_denom"])
    total, total_low, total_high = _summed_cause_interval(outcome, cause, best["lag"])

    payload = _series_payload(
        prepared,
        test=f"Granger causality: does past {cause_name} help forecast {outcome_name}?",
        direction=f"{cause_name} -> {outcome_name}",
        cause=cause_name,
        outcome=outcome_name,
        max_lag=max_lag,
        differences_applied=differences,
        adf=adf_results,
        best_lag=best["lag"],
        any_lag_significant=any(row["significant_at_0.05"] for row in rows),
        adjustment="Benjamini-Hochberg across the tested lags",
        lags=rows,
        effect_size=effect_size(
            "partial eta squared",
            eta,
            "variance_explained",
            at_lag=best["lag"],
            definition="share of the outcome's otherwise-unexplained variance that the "
            "lagged cause accounts for",
        ),
        confidence_interval=interval(
            total_low,
            total_high,
            of=f"the summed coefficient on {best['lag']} lag(s) of {cause_name}",
            point_estimate=total,
        ),
        assumptions=assumptions(
            prepared.assumption(),
            *(
                Assumption(
                    f"Stationarity of {name}",
                    entry["rejects_unit_root"],
                    f"ADF p = {entry['p_value']:.4g} after {differences} difference(s)",
                    entry["statistic"],
                    entry["p_value"],
                )
                for name, entry in adf_results.items()
            ),
            Assumption(
                "No omitted common driver",
                None,
                "the test compares two forecasts of the outcome and cannot see a third "
                "series that drives both; a confounder that leads both would produce this "
                "same result",
            ),
        ),
    )
    notes = prepared.notes() + exclusion_note(prepared.n_excluded) + [GRANGER_DISCLAIMER]
    if differences:
        notes.insert(
            1,
            f"Both {outcome_name} and {cause_name} were differenced {differences} time(s) to "
            f"reach stationarity, and every result below is about those differences — "
            f"period-to-period changes — rather than the levels.",
        )
    notes.append(
        f"P-values are adjusted by Benjamini-Hochberg across the {len(rows)} lag(s) tested; "
        f"read p_value_adjusted, not p_value."
    )
    return frame_to_result(
        pd.DataFrame(rows).drop(columns=["p_value_is_bound"]),
        op="granger_causality",
        label=label,
        n=len(frame),
        n_excluded=prepared.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


def _resolve_max_lag(requested: Any, n: int) -> int:
    """Lags to test, bounded so the unrestricted model keeps degrees of freedom."""
    ceiling = max(1, min(int(n * MAX_LAG_FRACTION) // 2, MAX_LAGS))
    if requested is None:
        return min(4, ceiling)
    asked = int(requested)
    if asked < 1:
        raise ExecutionError(f"granger_causality: max_lag must be at least 1, got {asked}")
    if asked > ceiling:
        raise ExecutionError(
            f"granger_causality: max_lag {asked} is too large for a {n}-period series; "
            f"at most {ceiling} lag(s) leave the unrestricted model enough degrees of freedom"
        )
    return asked


def _granger_rows(tests: dict[Any, Any]) -> list[dict[str, Any]]:
    rows = []
    for lag in sorted(tests, key=int):
        f_statistic, raw_p, df_denom, df_num = tests[lag][0]["ssr_ftest"]
        p_value, is_bound = _bounded_p(float(raw_p), ALPHA / 1e8)
        rows.append(
            {
                "lag": int(lag),
                "f_statistic": float(f_statistic),
                "df_num": float(df_num),
                "df_denom": float(df_denom),
                "p_value": p_value,
                "p_value_is_bound": is_bound,
                "partial_eta_squared": _partial_eta_squared(
                    float(f_statistic), float(df_num), float(df_denom)
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_FREQ_PARAM = Param("freq", "choice", choices=SERIES_FREQS)
_AGG_PARAM = Param("agg", "agg")
_SERIES_RULE = (
    "The series is put on a regular grid before anything is fitted: rows sharing a "
    "timestamp are collapsed by 'agg' (mean unless you say otherwise), 'freq' is inferred "
    "from the spacing when you omit it, and periods with no observation are interpolated "
    "and counted. A series with more than a fifth of its periods empty is refused — use "
    "resample at a coarser frequency first."
)


def _check_arima(params: dict[str, Any], roles: Any) -> list[str]:
    problems: list[str] = []
    seasonal = [key for key in ("P", "D", "Q") if key in params]
    if seasonal and "seasonal_period" not in params:
        problems.append(
            f"arima: a seasonal order ({', '.join(seasonal)}) requires 'seasonal_period', "
            f"the cycle length in periods (12 for monthly data with a yearly cycle)"
        )
    if "seasonal_period" in params and not seasonal:
        problems.append(
            "arima: 'seasonal_period' has no effect without a seasonal order — set P, D or Q"
        )
    if params.get("p") == 0 and params.get("q") == 0 and not seasonal:
        problems.append(
            "arima: p and q are both zero, so the model has no dynamics to estimate; "
            "use decompose or stationarity_test to describe the series instead"
        )
    return problems


def _check_decompose(params: dict[str, Any], roles: Any) -> list[str]:
    if params.get("freq") == "YE" and "seasonal_period" not in params:
        return [
            "decompose: yearly data has no cycle shorter than one observation, so "
            "'seasonal_period' must be given explicitly"
        ]
    return []


TIMESERIES_OPERATION_DEFS: dict[str, OperationDef] = {
    "decompose": OperationDef(
        5,
        "Split a series into trend, repeating seasonal pattern and remainder (STL, or a "
        "classical decomposition when the series is too short). Reports how strong the "
        "trend and the seasonality are, on a 0-1 scale.",
        (
            Param("date", "datetime", required=True),
            Param("value", "numeric", required=True),
            _FREQ_PARAM,
            Param("seasonal_period", "int"),
            _AGG_PARAM,
        ),
        requires=(
            "seasonal_period defaults to the cycle the frequency implies (7 for daily, 52 "
            "for weekly, 12 for monthly, 4 for quarterly) and must be given explicitly for "
            "yearly data. The series needs at least two full cycles. " + _SERIES_RULE
        ),
        check=_check_decompose,
    ),
    "stationarity_test": OperationDef(
        5,
        "Whether a series is stationary, by ADF and KPSS together. Their nulls are "
        "opposites, so running both distinguishes a unit root from a deterministic trend "
        "and says whether to difference or to detrend.",
        (
            Param("date", "datetime", required=True),
            Param("value", "numeric", required=True),
            _FREQ_PARAM,
            _AGG_PARAM,
            Param("regression", "choice", choices=("c", "ct")),
        ),
        requires=(
            "regression=c tests around a constant (the default); regression=ct tests around "
            "a constant and a linear trend — use it when the series visibly trends. " + _SERIES_RULE
        ),
    ),
    "autocorrelation": OperationDef(
        5,
        "ACF and PACF with Bartlett confidence bands, plus a Ljung-Box test of whether the "
        "series has any autocorrelation at all. The shape of the two tells you which ARIMA "
        "order to fit.",
        (
            Param("date", "datetime", required=True),
            Param("value", "numeric", required=True),
            _FREQ_PARAM,
            _AGG_PARAM,
            Param("lags", "int"),
        ),
        requires=(
            "lags defaults to the Box-Jenkins rule of thumb and is capped at a quarter of "
            "the series length; the result says when it was capped. " + _SERIES_RULE
        ),
    ),
    "arima": OperationDef(
        5,
        "Fit an ARIMA or seasonal ARIMA model and, with forecast_periods, forecast from it "
        "with prediction intervals. Reports coefficients with standard errors, AIC/BIC, and "
        "a Ljung-Box test of the residuals.",
        (
            Param("date", "datetime", required=True),
            Param("value", "numeric", required=True),
            _FREQ_PARAM,
            _AGG_PARAM,
            Param("p", "count", required=True),
            Param("d", "count", required=True),
            Param("q", "count", required=True),
            Param("P", "count"),
            Param("D", "count"),
            Param("Q", "count"),
            Param("seasonal_period", "int"),
            Param("forecast_periods", "int"),
        ),
        requires=(
            "p, d and q are non-negative and may be zero. Any of P, D or Q requires "
            "seasonal_period, and seasonal_period alone does nothing. Use stationarity_test "
            "to choose d and autocorrelation to choose p and q. forecast_periods is optional "
            "and applies only here: every forecast row is labelled and carries a prediction "
            "interval which must be reported with it. " + _SERIES_RULE
        ),
        check=_check_arima,
    ),
    "granger_causality": OperationDef(
        5,
        "Whether past values of one series improve the forecast of another (predictive "
        "precedence, NOT causation). Reports an F-test per lag with Benjamini-Hochberg "
        "adjusted p-values.",
        (
            Param("date", "datetime", required=True),
            Param("value", "numeric", required=True),
            Param("cause", "numeric", required=True),
            _FREQ_PARAM,
            _AGG_PARAM,
            Param("max_lag", "int"),
        ),
        requires=(
            "'cause' is the series suspected of leading and 'value' the one it may lead; "
            "they must differ. Both must be stationary, and both are differenced together "
            "(up to twice) when they are not — the result then describes the differences, "
            "not the levels, and says so. A result here never supports a causal claim. "
            + _SERIES_RULE
        ),
    ),
}


# Registered into the executor's dispatch table.
TIMESERIES_OPERATIONS = {
    "decompose": op_decompose,
    "stationarity_test": op_stationarity_test,
    "autocorrelation": op_autocorrelation,
    "arima": op_arima,
    "granger_causality": op_granger_causality,
}
