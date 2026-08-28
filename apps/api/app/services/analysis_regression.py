"""Tier 4: regression — what moves the outcome, holding the rest fixed.

Where Tier 3 asks whether two groups differ, this module asks how much of an
outcome one variable accounts for once the others are held constant. Four
models cover the shapes an uploaded dataset usually has: ``ols`` for a
continuous outcome, ``logit`` for a binary one, ``count_model`` for events per
unit of exposure, and ``quantile_regression`` for the tails a mean hides.

It declares its operations in ``REGRESSION_OPERATION_DEFS`` and their
implementations in ``REGRESSION_OPERATIONS``, keyed by the same names.
:mod:`app.services.analysis_spec` merges the first into the validated whitelist
and :mod:`app.services.analysis_executor` merges the second into the dispatch
table, so this module is the only place a tier-4 operation is defined. The
shared preparation — design matrices, dummy coding, diagnostics, coefficient
tables — lives in :mod:`app.services.analysis_regression_core`.

Regression is the point in this pipeline where a wrong answer looks most like a
right one. A model fitted on data that cannot support it does not fail; it
returns a full table of estimates, standard errors and stars. So every
operation here refuses first and estimates second: too few rows for the
parameters, a constant or duplicated regressor, a categorical with more levels
than the sample can carry, an outcome that is a linear function of its own
regressors, a logit whose outcome is perfectly separated. Each raises with the
numbers that made it impossible, so the planner can choose something else.

Every result carries the same four things beside its coefficients — an effect
size, confidence intervals, assumption checks, and n with the count of rows
dropped listwise and why. Rows are never imputed.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.tools.sm_exceptions import (
    IterationLimitWarning,
    PerfectSeparationError,
    PerfectSeparationWarning,
)

from app.services.analysis_prep import assumptions, significant
from app.services.analysis_registry import OperationDef, Param
from app.services.analysis_regression_core import (
    INTERCEPT,
    MAX_DUMMY_COLUMNS,
    ODDS_RATIO,
    RATE_RATIO,
    ROBUST_CHOICES,
    Design,
    build_design,
    coefficient_frame,
    dispersion_assumption,
    events_per_predictor_assumption,
    guard_perfect_fit,
    homoskedasticity_assumption,
    independence_assumption,
    influence_assumption,
    multicollinearity_assumption,
    p_value,
    residual_normality_assumption,
    robust_choice,
    unscaled_effect,
    vif_rows,
)
from app.services.analysis_result import ExecutionError, OperationResult, frame_to_result
from app.services.analysis_stats import Assumption, effect_size, interval

# A log-odds standard error this large means the coefficient is not identified:
# it puts the odds ratio's interval across fifty orders of magnitude either way.
# statsmodels reports separation as a warning and returns such a fit rather
# than raising, so this is the second half of the separation guard.
MAX_LOG_ODDS_STANDARD_ERROR = 25.0

# Chinn's conversion: dividing a log-odds ratio by pi/sqrt(3) — the standard
# deviation of the logistic distribution — puts it on Cohen's d scale, which is
# the only benchmark a logit coefficient has.
LOGISTIC_TO_COHEN_D = math.sqrt(3) / math.pi

COUNT_FAMILIES = ("poisson", "negative_binomial")

DEFAULT_TAU = 0.5

# The interior-point iteration behind quantile regression defaults to 1,000
# steps. Raised here because hitting the cap is reported rather than refused,
# and a cap that is rarely reached makes that report meaningful.
QUANTREG_MAX_ITER = 10_000

# A quantile fit is estimated from the observations near the requested quantile,
# not from the whole sample: at tau = 0.95 on 20 rows, one observation carries
# the line. Ten per parameter is the same order of magnitude as the events-per-
# predictor rule for logistic regression, and rests on the same reasoning.
MIN_TAIL_OBSERVATIONS_PER_TERM = 10


# ---------------------------------------------------------------------------
# Shared result assembly
# ---------------------------------------------------------------------------


def _focal_term(design: Design) -> str:
    """The regressor a headline interval describes.

    The first term of the first regressor the spec named — the model has no
    opinion about which coefficient matters, but the question that produced the
    spec named one first, and every coefficient's interval is in the table.
    """
    return design.terms[0]


def _row_for(table: pd.DataFrame, term: str) -> dict[str, Any]:
    match = table.loc[table["term"] == term]
    return dict(match.iloc[0]) if len(match) else {}


def _base_payload(design: Design, table: pd.DataFrame, model: str) -> dict[str, Any]:
    """The half of the payload that is the same for every model here."""
    return {
        "model": model,
        "outcome": design.outcome,
        "regressors": list(design.regressors),
        "n": design.n,
        "n_excluded": design.n_excluded,
        "coefficients": table.to_dict("records"),
        "reference_levels": dict(design.reference_levels),
        "vif": vif_rows(design),
    }


# ---------------------------------------------------------------------------
# Ordinary least squares
# ---------------------------------------------------------------------------


def op_ols(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    outcome, regressors = params["y"], list(params["x"])
    robust = robust_choice(params, default="HC3")
    design = build_design(df, op="ols", outcome=outcome, regressors=regressors)

    values = design.outcome_values()
    model = sm.OLS(values, design.exog)
    # use_t keeps the reported statistic a t and the interval a t interval when
    # a robust covariance is used; statsmodels otherwise switches silently to
    # the normal, which would label a z as a t in the coefficient table.
    fit = model.fit(cov_type=robust, use_t=True) if robust else model.fit()
    residuals = np.asarray(fit.resid, dtype=float)
    guard_perfect_fit("ols", outcome, values, residuals)

    table = coefficient_frame(fit, statistic="t")
    focal = _focal_term(design)
    focal_row = _row_for(table, focal)
    ss_residual = float(residuals @ residuals)

    payload = _base_payload(
        design, table, f"Ordinary least squares: {outcome} on {', '.join(regressors)}"
    )
    payload |= {
        "standard_errors": robust or "classical",
        "statistic_column": "t",
        "df_model": int(fit.df_model),
        "df_resid": int(fit.df_resid),
        "r_squared": float(fit.rsquared),
        "adj_r_squared": float(fit.rsquared_adj),
        "f_statistic": float(fit.fvalue),
        "f_p_value": p_value(fit.f_pvalue),
        "significant_at_0.05": significant(float(fit.f_pvalue)),
        "rmse": math.sqrt(ss_residual / design.n),
        "residual_std_error": math.sqrt(ss_residual / float(fit.df_resid)),
        "aic": float(fit.aic),
        "bic": float(fit.bic),
        "confidence_interval": interval(
            focal_row.get("ci_low"), focal_row.get("ci_high"), of=f"the coefficient on {focal}"
        ),
        "effect_size": effect_size("R squared", float(fit.rsquared), "variance_explained"),
        "assumptions": assumptions(
            multicollinearity_assumption(payload["vif"]),
            homoskedasticity_assumption(residuals, fit.model.exog, robust=robust),
            independence_assumption(residuals),
            residual_normality_assumption(residuals, design.n),
            influence_assumption(fit, design.n),
        ),
    }

    notes = design.notes()
    notes.append(
        f"Standard errors are {robust} (heteroskedasticity-consistent); the coefficients "
        f"themselves do not depend on that choice."
        if robust
        else "Classical standard errors: valid only if the residual spread is constant."
    )
    return frame_to_result(
        table,
        op="ols",
        label=label,
        n=design.n,
        n_excluded=design.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# Logistic regression
# ---------------------------------------------------------------------------


def _matches(series: pd.Series, value: Any) -> pd.Series:
    """Rows where the outcome equals *value*, comparing as text then as number."""
    as_text = series.astype(str) == str(value)
    if bool(as_text.any()):
        return as_text
    # "1" against a float column of 1.0 would otherwise match nothing, and a
    # rate of zero reads as a finding rather than as a spelling mistake.
    try:
        target = float(value)
    except (TypeError, ValueError):
        return as_text
    return pd.to_numeric(series, errors="coerce") == target


def _binary_outcome(design: Design, success: Any) -> tuple[np.ndarray, int]:
    values = design.frame[design.outcome]
    matched = _matches(values, success)
    successes = int(matched.sum())

    if successes == 0:
        categories = sorted({str(value) for value in values.unique()})
        raise ExecutionError(
            f"logit: {success!r} never occurs in {design.outcome!r} among the {design.n} "
            f"usable row(s), so the outcome is constant at zero. Values present: "
            f"{categories[:20]}"
        )
    if successes == design.n:
        raise ExecutionError(
            f"logit: every one of the {design.n} usable row(s) has {design.outcome} == "
            f"{success!r}, so the outcome does not vary and there is nothing to model"
        )
    return matched.to_numpy(dtype=float), successes


def _fit_logit(values: np.ndarray, design: Design, robust: str | None) -> Any:
    """Fit, then refuse the fits statsmodels returns instead of raising on."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            model = sm.Logit(values, design.exog)
            fit = model.fit(disp=0, cov_type=robust) if robust else model.fit(disp=0)
        except (PerfectSeparationError, np.linalg.LinAlgError) as exc:
            raise ExecutionError(
                f"logit: the outcome is perfectly separated by {list(design.regressors)}, "
                f"so no finite coefficient exists ({exc})"
            ) from exc
        separated = any(issubclass(entry.category, PerfectSeparationWarning) for entry in caught)

    errors = np.asarray(fit.bse, dtype=float)
    worst = float(np.max(np.abs(errors))) if errors.size else math.nan
    converged = bool(fit.mle_retvals.get("converged", True))
    if (
        separated
        or not converged
        or not math.isfinite(worst)
        or worst > MAX_LOG_ODDS_STANDARD_ERROR
    ):
        raise ExecutionError(
            f"logit: the outcome is perfectly (or almost perfectly) separated by "
            f"{list(design.regressors)}, so no finite coefficient exists and the standard "
            f"errors are arbitrary (largest {worst:.4g}). Drop the separating regressor, "
            f"collapse its categories, or compare the groups with proportion_test instead."
        )
    return fit


def op_logit(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    outcome, regressors = params["y"], list(params["x"])
    if "success_value" not in params:
        raise ExecutionError(
            "logit: requires 'success_value', the outcome category that counts as a success"
        )
    success = params["success_value"]
    robust = robust_choice(params, default="none")
    design = build_design(
        df, op="logit", outcome=outcome, regressors=regressors, numeric_outcome=False
    )

    values, successes = _binary_outcome(design, success)
    fit = _fit_logit(values, design, robust)

    table = coefficient_frame(fit, statistic="z", ratio=ODDS_RATIO)
    focal = _focal_term(design)
    focal_row = _row_for(table, focal)
    log_likelihood, null_log_likelihood = float(fit.llf), float(fit.llnull)

    payload = _base_payload(
        design,
        table,
        f"Logistic regression: P({outcome} == {success!r}) on {', '.join(regressors)}",
    )
    payload |= {
        "success_value": str(success),
        "successes": successes,
        "base_rate": successes / design.n,
        "standard_errors": robust or "classical (observed information)",
        "statistic_column": "z",
        "df_model": int(fit.df_model),
        "df_resid": int(fit.df_resid),
        "log_likelihood": log_likelihood,
        "null_log_likelihood": null_log_likelihood,
        "pseudo_r_squared": float(fit.prsquared),
        "pseudo_r_squared_kind": "McFadden; not a share of variance, and small values are normal",
        "llr_statistic": float(fit.llr),
        "llr_p_value": p_value(fit.llr_pvalue),
        "significant_at_0.05": significant(float(fit.llr_pvalue)),
        "aic": float(fit.aic),
        "bic": float(fit.bic),
        "confidence_interval": interval(
            focal_row.get(ODDS_RATIO.low),
            focal_row.get(ODDS_RATIO.high),
            of=f"the odds ratio for {focal}",
        ),
        "effect_size": effect_size(
            "Cohen's d (converted from the log-odds)",
            float(focal_row.get("coefficient", math.nan)) * LOGISTIC_TO_COHEN_D,
            "cohen_d",
            of=focal,
            odds_ratio=focal_row.get(ODDS_RATIO.value),
        ),
        "assumptions": assumptions(
            multicollinearity_assumption(payload["vif"]),
            events_per_predictor_assumption(successes, design.n - successes, len(design.terms)),
            Assumption(
                "Convergence and separation",
                True,
                f"the fit converged and every standard error is finite "
                f"(largest {float(np.max(np.abs(np.asarray(fit.bse, dtype=float)))):.4g})",
            ),
            Assumption(
                "Independence of observations",
                None,
                "a logit assumes one independent row per subject; repeated measures or "
                "clustered sampling need a model that says so, and would make these "
                "standard errors too small",
            ),
        ),
    }

    notes = design.notes()
    notes.append(
        f"Odds ratios are exp(coefficient); {successes} of {design.n} rows "
        f"({successes / design.n:.1%}) are successes."
    )
    if robust and robust != "HC0":
        notes.append(
            f"statsmodels applies the same White sandwich estimator to every HC variant on "
            f"a maximum-likelihood fit, so {robust} is not distinguished from HC0 here."
        )
    return frame_to_result(
        table,
        op="logit",
        label=label,
        n=design.n,
        n_excluded=design.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# Count models
# ---------------------------------------------------------------------------


def _count_inputs(
    design: Design, exposure_column: str | None
) -> tuple[np.ndarray, np.ndarray | None]:
    values = design.outcome_values()
    smallest = float(values.min())
    if smallest < 0:
        raise ExecutionError(
            f"count_model: {design.outcome!r} contains negative values (smallest {smallest:g}); "
            f"a count model needs non-negative counts. Use ols for a signed outcome."
        )
    if exposure_column is None:
        return values, None

    exposure = design.frame[exposure_column].to_numpy(dtype=float)
    if float(exposure.min()) <= 0:
        raise ExecutionError(
            f"count_model: exposure {exposure_column!r} has non-positive values "
            f"(smallest {float(exposure.min()):g}); log(exposure) is undefined there"
        )
    return values, exposure


def _fit_negative_binomial(values: np.ndarray, design: Design, exposure: np.ndarray | None) -> Any:
    with warnings.catch_warnings():
        # Optimizer chatter on the way to a converged fit is not information;
        # the convergence flag below is.
        warnings.simplefilter("ignore")
        model = sm.NegativeBinomial(values, design.exog, loglike_method="nb2", exposure=exposure)
        fit = model.fit(disp=0)
    if not bool(fit.mle_retvals.get("converged", True)):
        raise ExecutionError(
            "count_model: the negative binomial fit did not converge, so its coefficients "
            "and standard errors cannot be trusted. Try family=poisson, or fewer regressors."
        )
    return fit


def _poisson_dispersion(fit: Any) -> tuple[float, float]:
    return float(fit.pearson_chi2), float(fit.df_resid)


def _negative_binomial_dispersion(
    fit: Any, values: np.ndarray
) -> tuple[float, float, dict[str, Any]]:
    """Pearson chi-square under the NB2 variance mu + alpha*mu^2."""
    alpha = float(fit.params["alpha"])
    mu = np.asarray(fit.predict(), dtype=float)
    variance = mu + alpha * mu**2
    chi_square = (
        float(np.sum((values - mu) ** 2 / variance)) if bool((variance > 0).all()) else math.nan
    )
    detail = {
        "alpha": alpha,
        "alpha_std_err": float(fit.bse["alpha"]),
        "note": "alpha is the NB2 overdispersion parameter; alpha = 0 is the Poisson",
    }
    return chi_square, float(fit.df_resid), detail


def op_count_model(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    outcome, regressors = params["y"], list(params["x"])
    family = str(params.get("family", "poisson"))
    if family not in COUNT_FAMILIES:
        raise ExecutionError(f"count_model: unknown family {family!r} (allowed: {COUNT_FAMILIES})")
    exposure_column = params.get("exposure")
    design = build_design(
        df,
        op="count_model",
        outcome=outcome,
        regressors=regressors,
        also_required=(exposure_column,) if exposure_column else (),
    )
    values, exposure = _count_inputs(design, exposure_column)

    dispersion: dict[str, Any] = {}
    if family == "poisson":
        fit = sm.GLM(values, design.exog, family=sm.families.Poisson(), exposure=exposure).fit()
        chi_square, df_resid = _poisson_dispersion(fit)
        exclude: tuple[str, ...] = ()
        model_name = "Poisson regression (log link)"
    else:
        fit = _fit_negative_binomial(values, design, exposure)
        chi_square, df_resid, dispersion = _negative_binomial_dispersion(fit, values)
        exclude = ("alpha",)
        model_name = "Negative binomial regression (NB2, log link)"

    table = coefficient_frame(fit, statistic="z", exclude=exclude, ratio=RATE_RATIO)
    focal = _focal_term(design)
    focal_row = _row_for(table, focal)
    check = dispersion_assumption(chi_square, df_resid, family=family)
    dispersion |= {"pearson_chi2": chi_square, "df_resid": df_resid, "ratio": check.statistic}

    log_likelihood, null_log_likelihood = float(fit.llf), float(fit.llnull)
    payload = _base_payload(design, table, f"{model_name}: {outcome} on {', '.join(regressors)}")
    payload |= {
        "family": family,
        "exposure": exposure_column,
        "statistic_column": "z",
        "df_model": int(fit.df_model),
        "df_resid": int(df_resid),
        "mean_outcome": float(values.mean()),
        "variance_outcome": float(values.var(ddof=1)),
        "log_likelihood": log_likelihood,
        "null_log_likelihood": null_log_likelihood,
        "pseudo_r_squared": 1 - log_likelihood / null_log_likelihood,
        "pseudo_r_squared_kind": "McFadden; not a share of variance",
        "aic": float(fit.aic),
        "bic": float(fit.bic),
        "dispersion": dispersion,
        "confidence_interval": interval(
            focal_row.get(RATE_RATIO.low),
            focal_row.get(RATE_RATIO.high),
            of=f"the incidence rate ratio for {focal}",
        ),
        "effect_size": unscaled_effect(
            "incidence rate ratio",
            focal_row.get(RATE_RATIO.value),
            of=focal,
            benchmark="a rate ratio has no conventional magnitude scale; 1.0 is no effect",
        ),
        "assumptions": assumptions(
            check,
            multicollinearity_assumption(payload["vif"]),
            _whole_number_assumption(values),
        ),
    }

    notes = design.notes()
    notes.append(
        "Coefficients are on the log scale; the incidence rate ratio column is "
        "exp(coefficient) — the multiplicative change in the expected count."
    )
    if exposure_column:
        notes.append(
            f"log({exposure_column}) enters as an offset, so the coefficients describe rates "
            f"per unit of {exposure_column} rather than raw counts."
        )
    if family == "poisson" and check.passed is False:
        notes.append(
            "The Poisson variance assumption fails on this data; re-run with "
            "family=negative_binomial, which estimates the extra dispersion instead of "
            "assuming it away."
        )
    return frame_to_result(
        table,
        op="count_model",
        label=label,
        n=design.n,
        n_excluded=design.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


def _whole_number_assumption(values: np.ndarray) -> Assumption:
    fractional = int(np.sum(np.abs(values - np.round(values)) > 1e-9))
    name = "Whole-number counts"
    if fractional == 0:
        return Assumption(name, True, f"all {values.size} outcome values are whole numbers", 0.0)
    return Assumption(
        name,
        False,
        f"{fractional} of {values.size} outcome values are not whole numbers, so this is a "
        f"quasi-likelihood fit rather than a count model; the coefficients still describe "
        f"proportional change, but the likelihood-based statistics are approximate",
        float(fractional),
    )


# ---------------------------------------------------------------------------
# Quantile regression
# ---------------------------------------------------------------------------


def _tail_assumption(n: int, tau: float, parameters: int) -> Assumption:
    """Whether enough of the sample sits in the tail the quantile describes."""
    name = "Observations beyond the requested quantile"
    available = n * min(tau, 1 - tau)
    needed = MIN_TAIL_OBSERVATIONS_PER_TERM * parameters
    passed = available >= needed
    detail = (
        f"about {available:.4g} of {n} row(s) lie beyond tau = {tau:g}, against "
        f"{needed} wanted for {parameters} parameter(s)"
    )
    detail += (
        "; enough to estimate the quantile"
        if passed
        else "; the fit rests on a handful of observations and will move a lot with any of them"
    )
    return Assumption(name, passed, detail, float(available))


def op_quantile_regression(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    outcome, regressors = params["y"], list(params["x"])
    tau = float(params.get("tau", DEFAULT_TAU))
    if not 0.0 < tau < 1.0:
        raise ExecutionError(
            f"quantile_regression: tau must be strictly between 0 and 1, got {tau}"
        )
    design = build_design(df, op="quantile_regression", outcome=outcome, regressors=regressors)

    values = design.outcome_values()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fit = QuantReg(values, design.exog).fit(q=tau, max_iter=QUANTREG_MAX_ITER)
    hit_limit = any(issubclass(entry.category, IterationLimitWarning) for entry in caught)
    residuals = np.asarray(fit.resid, dtype=float)
    guard_perfect_fit("quantile_regression", outcome, values, residuals)

    table = coefficient_frame(fit, statistic="t")
    focal = _focal_term(design)
    focal_row = _row_for(table, focal)

    payload = _base_payload(
        design,
        table,
        f"Quantile regression at tau = {tau:g}: {outcome} on {', '.join(regressors)}",
    )
    payload |= {
        "tau": tau,
        "statistic_column": "t",
        "standard_errors": "Huber sandwich (statsmodels QuantReg default)",
        "df_model": int(fit.df_model),
        "df_resid": int(fit.df_resid),
        "pseudo_r_squared": float(fit.prsquared),
        "pseudo_r_squared_kind": "Koenker-Machado; goodness of fit at this quantile only",
        "share_below_fit": float(np.mean(residuals < 0)),
        "confidence_interval": interval(
            focal_row.get("ci_low"), focal_row.get("ci_high"), of=f"the coefficient on {focal}"
        ),
        "effect_size": unscaled_effect(
            "pseudo R² (Koenker-Machado)",
            float(fit.prsquared),
            of=f"the tau = {tau:g} fit",
            benchmark="fit at one quantile; Cohen's variance-explained cutoffs do not apply",
        ),
        "assumptions": assumptions(
            multicollinearity_assumption(payload["vif"]),
            _tail_assumption(design.n, tau, design.n_parameters),
            Assumption(
                "Convergence",
                not hit_limit,
                f"the iteration limit of {QUANTREG_MAX_ITER} was reached, so treat these "
                f"estimates as approximate"
                if hit_limit
                else "the interior-point iteration converged",
                float(QUANTREG_MAX_ITER),
            ),
            Assumption(
                "Interpretation",
                None,
                f"these coefficients describe the {tau:g} quantile of {outcome}, not its "
                f"mean; the model assumes no particular error distribution and is robust to "
                f"outliers in the outcome, but its standard errors do assume the residual "
                f"density near the quantile is well estimated",
            ),
        ),
    }

    notes = design.notes()
    notes.append(
        f"Each coefficient is the change in the {tau:g} quantile of {outcome} per unit of the "
        f"regressor — a different question from the change in its mean."
    )
    return frame_to_result(
        table,
        op="quantile_regression",
        label=label,
        n=design.n,
        n_excluded=design.n_excluded,
        notes=notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# Declared rules
# ---------------------------------------------------------------------------


def _regression_problems(params: dict[str, Any], roles: Any) -> list[str]:
    """Rules every model here shares, checked before anything is executed."""
    outcome, regressors = params.get("y"), params.get("x")
    if not isinstance(outcome, str) or not isinstance(regressors, list):
        return []  # parameter-kind validation has already reported this

    problems: list[str] = []
    if outcome in regressors:
        problems.append(f"the outcome {outcome!r} cannot also be a regressor; remove it from 'x'")
    repeated = sorted({name for name in regressors if regressors.count(name) > 1})
    if repeated:
        problems.append(f"regressor(s) {repeated} are listed more than once in 'x'")
    if outcome in roles.datetime:
        problems.append(f"the outcome {outcome!r} is a date/time column, which cannot be modelled")

    for name in regressors:
        if name in roles.datetime:
            problems.append(
                f"regressor {name!r} is a date/time column; regression over raw dates is not "
                f"supported — resample to a numeric measure of time first"
            )
        known = roles.categories.get(str(name))
        if known and len(known) - 1 > MAX_DUMMY_COLUMNS:
            problems.append(
                f"regressor {name!r} has {len(known)} distinct levels, which would add "
                f"{len(known) - 1} indicator columns; the limit is {MAX_DUMMY_COLUMNS}"
            )
    return problems


def _check_ols(params: dict[str, Any], roles: Any) -> list[str]:
    return _regression_problems(params, roles)


def _check_logit(params: dict[str, Any], roles: Any) -> list[str]:
    problems = _regression_problems(params, roles)
    outcome, success = params.get("y"), params.get("success_value")
    known = roles.categories.get(str(outcome)) if isinstance(outcome, str) else None
    if known and success is not None and str(success) not in known:
        problems.append(
            f"success_value {success!r} does not occur in {outcome!r} "
            f"(values: {sorted(known)[:20]})"
        )
    return problems


def _check_count_model(params: dict[str, Any], roles: Any) -> list[str]:
    problems = _regression_problems(params, roles)
    exposure, regressors = params.get("exposure"), params.get("x")
    if isinstance(exposure, str):
        if exposure == params.get("y"):
            problems.append(
                f"exposure {exposure!r} is also the outcome; the offset has to be a separate "
                f"measure of time or population at risk"
            )
        if isinstance(regressors, list) and exposure in regressors:
            problems.append(
                f"exposure {exposure!r} is also a regressor; it enters as a fixed log offset, "
                f"not as an estimated coefficient"
            )
    return problems


def _check_quantile_regression(params: dict[str, Any], roles: Any) -> list[str]:
    return _regression_problems(params, roles)


_SHARED_RULES = (
    f"'x' may mix numeric regressors and categorical predictors; a categorical column is "
    f"dummy-coded against its alphabetically first level, which is named in the result, and "
    f"may expand into at most {MAX_DUMMY_COLUMNS} indicator columns. The outcome must not "
    f"appear in 'x', no column may be listed twice, and date columns cannot be regressors. "
    f"Rows missing the outcome or any regressor are dropped listwise and counted."
)


REGRESSION_OPERATION_DEFS: dict[str, OperationDef] = {
    "ols": OperationDef(
        4,
        "Linear regression of a numeric outcome on several regressors at once, with "
        "heteroskedasticity-robust standard errors. Reports a coefficient table with "
        "confidence intervals, R², F, RMSE and AIC/BIC, plus VIF, Breusch-Pagan, "
        "Durbin-Watson, Jarque-Bera and Cook's distance diagnostics.",
        (
            Param("y", "numeric", required=True),
            Param("x", "columns", required=True),
            Param("robust", "choice", choices=ROBUST_CHOICES),
        ),
        requires=(
            _SHARED_RULES + " robust defaults to HC3, the most conservative small-sample "
            "correction; set robust=none only where the residual spread is known to be constant."
        ),
        check=_check_ols,
    ),
    "logit": OperationDef(
        4,
        "Logistic regression of a binary outcome. Reports log-odds coefficients and odds "
        "ratios with confidence intervals, McFadden's pseudo R², the likelihood-ratio test "
        "and the base rate. Refuses when the outcome is perfectly separated.",
        (
            Param("y", "column", required=True),
            Param("success_value", "value", required=True),
            Param("x", "columns", required=True),
            Param("robust", "choice", choices=ROBUST_CHOICES),
        ),
        requires=(
            _SHARED_RULES + " success_value is the outcome category that counts as a success, "
            "spelled exactly as it appears in the data; the outcome must contain both that "
            "value and something else. robust defaults to none, because the classical "
            "maximum-likelihood errors are the efficient ones for a correctly specified logit."
        ),
        check=_check_logit,
    ),
    "count_model": OperationDef(
        4,
        "Poisson or negative binomial regression for counts of events. Reports incidence "
        "rate ratios with confidence intervals and checks Poisson's equal-mean-and-variance "
        "assumption, naming the negative binomial when it fails.",
        (
            Param("y", "numeric", required=True),
            Param("x", "columns", required=True),
            Param("family", "choice", choices=COUNT_FAMILIES),
            Param("exposure", "numeric"),
        ),
        requires=(
            _SHARED_RULES + " The outcome must be non-negative counts. family defaults to "
            "poisson; use negative_binomial when the overdispersion check on a poisson fit "
            "fails. exposure is optional and applies only here: it is the time or population "
            "at risk per row, entered as a log offset so the coefficients describe rates, and "
            "it must be strictly positive and be neither the outcome nor a regressor."
        ),
        check=_check_count_model,
    ),
    "quantile_regression": OperationDef(
        4,
        "Regression of a quantile of the outcome rather than its mean — the model for "
        "'what moves the bottom decile', and for outcomes whose mean an outlier owns.",
        (
            Param("y", "numeric", required=True),
            Param("x", "columns", required=True),
            Param("tau", "proportion"),
        ),
        requires=(
            _SHARED_RULES + " tau is the quantile to fit and defaults to 0.5 (the median). "
            "A tau near 0 or 1 is estimated from the few observations in that tail, and the "
            "result says how many there were."
        ),
        check=_check_quantile_regression,
    ),
}


# Registered into the executor's dispatch table.
REGRESSION_OPERATIONS = {
    "ols": op_ols,
    "logit": op_logit,
    "count_model": op_count_model,
    "quantile_regression": op_quantile_regression,
}


__all__ = ["INTERCEPT", "REGRESSION_OPERATIONS", "REGRESSION_OPERATION_DEFS"]
