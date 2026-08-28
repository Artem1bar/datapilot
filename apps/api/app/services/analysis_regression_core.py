"""Shared plumbing behind the Tier 4 regression operations.

Four models — OLS, logit, Poisson/negative binomial, quantile regression —
differ in what they fit and agree on everything around it: which rows are
usable, how a categorical predictor becomes columns, how a coefficient table is
rendered, and which diagnostics have to travel with the estimates. That shared
half lives here so :mod:`app.services.analysis_regression` reads as four models
rather than as four copies of the same preparation.

The invariant this module holds is the one that separates a regression tool
from a plausible-looking one: **a design matrix the data cannot support is
refused, not fitted.** Three rows and three parameters, a regressor that never
varies, the same column supplied twice, an outcome that is an exact linear
function of its own regressors — none of these make statsmodels raise. Each
returns a complete coefficient table whose standard errors, t statistics and
p-values are artifacts of floating-point rounding rather than measurements of
anything. Every one of them raises here, naming the numbers, before a single
coefficient is estimated.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import OLSInfluence, variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, jarque_bera

from app.services.analysis_result import ExecutionError
from app.services.analysis_stats import (
    ALPHA,
    CLT_SAFE_N,
    CONFIDENCE_LEVEL,
    Assumption,
    json_safe,
)

# The intercept's name in every design matrix and coefficient table. Spelled so
# that it cannot be mistaken for a column of the uploaded file, and checked
# against the encoded terms in case a file has a column called exactly this.
INTERCEPT = "(Intercept)"

# Covariance estimators offered to the planner. "none" is the classical
# estimator; HC0-HC3 are the heteroskedasticity-consistent family, in
# increasing order of small-sample correction.
ROBUST_CHOICES = ("none", "HC0", "HC1", "HC2", "HC3")

# How many indicator columns one categorical regressor may expand into. A
# 400-level column would fit a model with 400 terms, most of them estimated
# from a handful of rows each — arithmetically possible and substantively
# meaningless. Refusing is more useful than returning it.
MAX_DUMMY_COLUMNS = 20

# Above this variance inflation factor, a coefficient's standard error is more
# than three times what orthogonal regressors would give it: the model as a
# whole may fit well while no individual coefficient in the correlated set is
# separately identified. Ten is the conventional screening cutoff.
VIF_LIMIT = 10.0

# How many of the worst VIFs to spell out in the assumption's detail; the full
# per-regressor list always goes into the payload.
MAX_RENDERED_VIF = 5

# Durbin-Watson is centred on 2 under independence. The 1.5/2.5 band is the
# conventional "nothing to see here" range.
DURBIN_WATSON_LOW = 1.5
DURBIN_WATSON_HIGH = 2.5

# Cook's distance flags an observation above 4/n, the conventional screening
# cutoff. That rule marks roughly 5% of a well-behaved normal sample (measured:
# 5.0% at n = 1000 rising to 6.1% at n = 50), so the verdict only trips above
# 10% — otherwise every clean regression would report an influence problem.
INFLUENCE_CUTOFF_MULTIPLE = 4.0
INFLUENCE_SHARE_LIMIT = 0.10

# Above this share of explained variance the residuals are rounding noise, not
# unexplained variation, and every standard error derived from them is an
# artifact of floating point. In real data it means the outcome is a linear
# function of its own regressors — a total regressed on its components — which
# is a tautology rather than a finding.
PERFECT_FIT_R_SQUARED = 1 - 1e-9

# A p-value that underflows to exactly 0.0 is not zero; it is smaller than an
# IEEE double can represent. Reporting it as 0 claims a certainty no test can
# support, so it is floored at the smallest normal double instead — the same
# reasoning as json_safe's significant-figure rule, one exponent further down.
P_VALUE_FLOOR = sys.float_info.min


def p_value(value: Any) -> float | None:
    """A p-value, floored so it can never serialize as exactly zero."""
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(as_float):
        return None
    return max(as_float, P_VALUE_FLOOR)


def exp_or_infinity(value: float) -> float:
    """``exp`` that saturates instead of raising, for ratio columns."""
    return float(np.exp(np.clip(float(value), -709.0, 709.0))) if math.isfinite(value) else math.nan


def unscaled_effect(name: str, value: float | None, *, of: str, benchmark: str) -> dict[str, Any]:
    """An effect size with no conventional magnitude scale.

    :func:`app.services.analysis_stats.effect_size` labels a value against
    Cohen's cutoffs. A rate ratio has no such benchmark, and inventing one
    would be worse than saying plainly that none exists.
    """
    return {
        "name": name,
        "value": json_safe(value),
        "magnitude": None,
        "of": of,
        "benchmark": benchmark,
    }


# ---------------------------------------------------------------------------
# Design matrix
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Design:
    """The rows and columns a regression will actually be fitted on."""

    frame: pd.DataFrame  # surviving rows, original columns
    exog: pd.DataFrame  # intercept plus coded regressors, float
    outcome: str
    regressors: tuple[str, ...]  # as the spec named them
    terms: tuple[str, ...]  # design columns other than the intercept
    reference_levels: Mapping[str, str]
    n: int
    n_excluded: int

    @property
    def n_parameters(self) -> int:
        return len(self.exog.columns)

    def outcome_values(self) -> np.ndarray:
        return self.frame[self.outcome].to_numpy(dtype=float)

    def notes(self) -> list[str]:
        """Everything a reader needs in order to interpret the table."""
        notes: list[str] = []
        if self.n_excluded:
            notes.append(
                f"Listwise deletion: {self.n_excluded} row(s) missing {self.outcome!r} or "
                f"any regressor were dropped, leaving {self.n}. Nothing was imputed."
            )
        if self.reference_levels:
            baselines = ", ".join(
                f"{column} = {level!r}" for column, level in sorted(self.reference_levels.items())
            )
            notes.append(
                f"Categorical baselines: {baselines}. Each indicator coefficient is the "
                f"difference from its baseline level, holding the other regressors fixed."
            )
        return notes


def build_design(
    df: pd.DataFrame,
    *,
    op: str,
    outcome: str,
    regressors: Sequence[str],
    also_required: Sequence[str] = (),
    numeric_outcome: bool = True,
) -> Design:
    """Assemble the design matrix, refusing anything it cannot support."""
    names = [outcome, *regressors, *also_required]
    missing = [name for name in names if name not in df.columns]
    if missing:
        raise ExecutionError(f"{op}: column(s) {missing} are not in the dataset")

    _reject_overlaps(op, outcome, regressors, also_required)

    frame = _usable_rows(df, names, outcome=outcome, numeric_outcome=numeric_outcome)
    used, excluded = len(frame), len(df) - len(frame)
    if used == 0:
        raise ExecutionError(
            f"{op}: no row has a value for {outcome!r} and every regressor at once, "
            f"so there is nothing to fit"
        )

    columns: dict[str, np.ndarray] = {INTERCEPT: np.ones(used, dtype=float)}
    references: dict[str, str] = {}
    for regressor in regressors:
        encoded, reference = _encode(op, regressor, frame[regressor], used)
        for term, values in encoded.items():
            if term == INTERCEPT:
                raise ExecutionError(
                    f"{op}: regressor {regressor!r} produces a term named {INTERCEPT}, "
                    f"which collides with the model's intercept; rename the column"
                )
            columns[term] = values
        if reference is not None:
            references[regressor] = reference

    exog = pd.DataFrame(columns, index=frame.index)
    if used <= len(exog.columns):
        raise ExecutionError(
            f"{op}: {used} usable row(s) for {len(exog.columns)} model parameter(s). "
            f"A regression needs more rows than parameters — at least "
            f"{len(exog.columns) + 1} here, and many more than that to be worth reading."
        )
    _reject_collinearity(op, exog)

    return Design(
        frame=frame,
        exog=exog,
        outcome=outcome,
        regressors=tuple(regressors),
        terms=tuple(str(c) for c in exog.columns if c != INTERCEPT),
        reference_levels=MappingProxyType(references),
        n=used,
        n_excluded=excluded,
    )


def _reject_overlaps(
    op: str, outcome: str, regressors: Sequence[str], also_required: Sequence[str]
) -> None:
    """A column may play exactly one role in a model."""
    if outcome in regressors:
        raise ExecutionError(
            f"{op}: the outcome {outcome!r} cannot also be a regressor; remove it from 'x'"
        )
    repeated = sorted({name for name in regressors if list(regressors).count(name) > 1})
    if repeated:
        raise ExecutionError(f"{op}: regressor(s) {repeated} are listed more than once in 'x'")
    for name in also_required:
        if name == outcome or name in regressors:
            raise ExecutionError(
                f"{op}: {name!r} is already the outcome or a regressor and cannot also be "
                f"the exposure"
            )


def _usable_rows(
    df: pd.DataFrame, names: Sequence[str], *, outcome: str, numeric_outcome: bool
) -> pd.DataFrame:
    """Listwise deletion over every column the model touches."""
    ordered = list(dict.fromkeys(names))
    frame = df.loc[:, ordered].copy()
    if numeric_outcome:
        # A non-numeric value in a numeric outcome is missing data, not a zero;
        # coercing first keeps it out of the fit through the same deletion.
        frame[outcome] = pd.to_numeric(frame[outcome], errors="coerce")
    return frame.dropna()


def _encode(
    op: str, name: str, series: pd.Series, used: int
) -> tuple[dict[str, np.ndarray], str | None]:
    """One regressor as design columns, plus its reference level if categorical."""
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        values = series.to_numpy(dtype=float)
        if float(np.ptp(values)) == 0.0:
            raise ExecutionError(
                f"{op}: regressor {name!r} is constant at {values[0]:g} across the "
                f"{used} usable row(s), so it carries no information"
            )
        return {name: values}, None

    as_text = series.astype(str)
    levels = sorted(as_text.unique())
    if len(levels) < 2:
        raise ExecutionError(
            f"{op}: regressor {name!r} has the single value {levels[0]!r} across the "
            f"{used} usable row(s), so it carries no information"
        )
    if len(levels) - 1 > MAX_DUMMY_COLUMNS:
        raise ExecutionError(
            f"{op}: regressor {name!r} has {len(levels)} distinct levels, which would add "
            f"{len(levels) - 1} indicator columns; the limit is {MAX_DUMMY_COLUMNS}. "
            f"Group the categories, or use a numeric measure of the same thing."
        )

    # The alphabetically first level is the reference, so the baseline is a
    # property of the data rather than of row order in the uploaded file.
    reference, rest = levels[0], levels[1:]
    encoded = {f"{name}[{level}]": (as_text == level).to_numpy(dtype=float) for level in rest}
    return encoded, reference


def _reject_collinearity(op: str, exog: pd.DataFrame) -> None:
    """Refuse a design whose columns are linearly dependent."""
    matrix = exog.to_numpy(dtype=float)
    if int(np.linalg.matrix_rank(matrix)) == matrix.shape[1]:
        return

    for position in range(1, matrix.shape[1]):
        before = int(np.linalg.matrix_rank(matrix[:, :position]))
        if int(np.linalg.matrix_rank(matrix[:, : position + 1])) == before:
            term = str(exog.columns[position])
            partner = _closest_partner(exog, matrix, position)
            with_whom = f" with {partner!r}" if partner else " with the other regressors"
            raise ExecutionError(
                f"{op}: {term!r} is perfectly collinear{with_whom}, so their separate "
                f"effects are not identified by any amount of data. Drop one of them."
            )
    raise ExecutionError(  # pragma: no cover - a rank deficit always has a first cause
        f"{op}: the regressors are linearly dependent and the model is not identified"
    )


def _closest_partner(exog: pd.DataFrame, matrix: np.ndarray, position: int) -> str | None:
    """The earlier column most nearly identical to the redundant one."""
    target = matrix[:, position]
    best_name, best_score = None, 0.0
    for earlier in range(position):
        candidate = matrix[:, earlier]
        if float(np.std(candidate)) == 0.0 or float(np.std(target)) == 0.0:
            continue
        score = abs(float(np.corrcoef(candidate, target)[0, 1]))
        if math.isfinite(score) and score > best_score:
            best_name, best_score = str(exog.columns[earlier]), score
    return best_name


def guard_perfect_fit(op: str, outcome: str, values: np.ndarray, residuals: np.ndarray) -> None:
    """Refuse a fit whose residuals are floating-point noise."""
    total = float(np.var(values))
    if total <= 0.0:
        raise ExecutionError(
            f"{op}: {outcome!r} is constant across all {values.size} usable row(s); "
            f"there is no variation to explain"
        )
    explained = 1.0 - float(np.var(residuals)) / total
    if explained >= PERFECT_FIT_R_SQUARED:
        raise ExecutionError(
            f"{op}: R² = {explained:.6f} — {outcome!r} is an exact linear function of the "
            f"regressors, so the residuals are rounding error and every standard error, "
            f"t statistic and p-value computed from them would be an artifact. This "
            f"usually means a total was regressed on its own components."
        )


# ---------------------------------------------------------------------------
# Coefficient table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RatioColumns:
    """Names for the exponentiated view of a coefficient and its interval."""

    value: str
    low: str
    high: str


ODDS_RATIO = RatioColumns("odds_ratio", "or_ci_low", "or_ci_high")
RATE_RATIO = RatioColumns("irr", "irr_ci_low", "irr_ci_high")


def coefficient_frame(
    fit: Any,
    *,
    statistic: str,
    exclude: Sequence[str] = (),
    ratio: RatioColumns | None = None,
) -> pd.DataFrame:
    """The coefficient table: estimate, error, statistic, p-value, interval."""
    bounds = fit.conf_int(alpha=1 - CONFIDENCE_LEVEL)
    rows: list[dict[str, Any]] = []
    for term in fit.params.index:
        if term in exclude:
            continue
        low = float(bounds.loc[term].iloc[0])
        high = float(bounds.loc[term].iloc[1])
        coefficient = float(fit.params[term])
        row: dict[str, Any] = {
            "term": str(term),
            "coefficient": coefficient,
            "std_err": float(fit.bse[term]),
            statistic: float(fit.tvalues[term]),
            "p_value": p_value(fit.pvalues[term]),
            "ci_low": low,
            "ci_high": high,
        }
        if ratio is not None:
            row[ratio.value] = exp_or_infinity(coefficient)
            row[ratio.low] = exp_or_infinity(low)
            row[ratio.high] = exp_or_infinity(high)
        rows.append(row)
    return pd.DataFrame(rows)


def robust_choice(params: dict[str, Any], *, default: str) -> str | None:
    """The requested covariance estimator, or None for the classical one."""
    choice = str(params.get("robust", default))
    if choice not in ROBUST_CHOICES:
        raise ExecutionError(f"unknown robust option {choice!r} (allowed: {list(ROBUST_CHOICES)})")
    return None if choice == "none" else choice


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def vif_rows(design: Design) -> list[dict[str, Any]]:
    """Variance inflation factor per design term, intercept excluded."""
    matrix = design.exog.to_numpy(dtype=float)
    rows: list[dict[str, Any]] = []
    for position, term in enumerate(design.exog.columns):
        if term == INTERCEPT:
            continue
        try:
            value = float(variance_inflation_factor(matrix, position))
        except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):  # pragma: no cover
            value = math.nan
        rows.append({"term": str(term), "vif": value})
    return rows


def multicollinearity_assumption(rows: Sequence[Mapping[str, Any]]) -> Assumption:
    """One verdict over every regressor's VIF; the full list is in the payload.

    Reported as a single check rather than one per regressor because the
    question a reader has is "is any coefficient here unidentified", and twenty
    separate entries would bury the one that matters.
    """
    name = "Multicollinearity (VIF)"
    usable = [row for row in rows if math.isfinite(float(row["vif"]))]
    if not usable:
        return Assumption(name, None, "no non-constant regressor to evaluate")

    ranked = sorted(usable, key=lambda row: float(row["vif"]), reverse=True)
    worst = float(ranked[0]["vif"])
    rendered = ", ".join(
        f"{row['term']} = {float(row['vif']):.3g}" for row in ranked[:MAX_RENDERED_VIF]
    )
    if len(ranked) > MAX_RENDERED_VIF:
        rendered += f", and {len(ranked) - MAX_RENDERED_VIF} more"

    passed = worst < VIF_LIMIT
    detail = f"VIF {rendered}" + (
        f"; all below {VIF_LIMIT:g}"
        if passed
        else (
            f"; {ranked[0]['term']} is above {VIF_LIMIT:g}, so the coefficients in the "
            f"correlated set are individually unstable even where the model as a whole fits"
        )
    )
    return Assumption(name, passed, detail, worst)


def homoskedasticity_assumption(
    residuals: np.ndarray, exog: np.ndarray, *, robust: str | None
) -> Assumption:
    """Breusch-Pagan: does the residual variance move with the fitted values?"""
    name = "Homoskedasticity (Breusch-Pagan)"
    try:
        statistic, lm_p, _, _ = het_breuschpagan(residuals, exog)
    except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - degenerate design
        return Assumption(name, None, "Breusch-Pagan could not be computed on this design")
    if not math.isfinite(lm_p):
        return Assumption(name, None, "Breusch-Pagan could not be computed on this design")

    passed = bool(lm_p >= ALPHA)
    if passed:
        detail = f"Lagrange multiplier p = {lm_p:.4g}; residual spread looks constant"
    else:
        detail = (
            f"Lagrange multiplier p = {lm_p:.4g}; residual spread varies with the fitted "
            f"values, so classical standard errors are wrong"
        )
        detail += (
            f", but the reported errors are {robust}, which stays valid under it"
            if robust
            else ". Re-run with robust=HC3."
        )
    return Assumption(name, passed, detail, float(statistic), float(lm_p))


def independence_assumption(residuals: np.ndarray) -> Assumption:
    """Durbin-Watson over the residuals in row order.

    Row order is the order of the uploaded file, so this reads as a test of
    autocorrelation only when that order means something — a time series, or a
    file sorted by something related to the outcome. The detail says so rather
    than letting a cross-sectional reader take 0.4 as a finding about time.
    """
    name = "Independence of residuals (Durbin-Watson)"
    statistic = float(durbin_watson(np.asarray(residuals, dtype=float)))
    if not math.isfinite(statistic):
        return Assumption(name, None, "Durbin-Watson could not be computed")

    passed = DURBIN_WATSON_LOW <= statistic <= DURBIN_WATSON_HIGH
    verdict = (
        "close to 2, so neighbouring residuals look independent"
        if passed
        else (
            "far from 2, so neighbouring rows have correlated residuals and the "
            "standard errors are too small"
        )
    )
    return Assumption(
        name,
        passed,
        f"d = {statistic:.4g}, {verdict}. Computed in the file's row order, so it is a "
        f"statement about time only when the rows are ordered in time.",
        statistic,
    )


def residual_normality_assumption(residuals: np.ndarray, n: int) -> Assumption:
    """Jarque-Bera on the residuals: skewness and kurtosis against a normal."""
    name = "Normality of residuals (Jarque-Bera)"
    array = np.asarray(residuals, dtype=float)
    if array.size < 2 or float(np.std(array)) == 0.0:
        return Assumption(name, None, "residuals have no variance; not testable")

    statistic, jb_p, skew, kurtosis = jarque_bera(array)
    if not math.isfinite(jb_p):
        return Assumption(name, None, "Jarque-Bera could not be computed")

    passed = bool(jb_p >= ALPHA)
    detail = f"p = {jb_p:.4g}, skewness {skew:.3g}, kurtosis {kurtosis:.3g}; "
    if passed:
        detail += "residuals are consistent with normality"
    elif n >= CLT_SAFE_N:
        # Coefficient estimates are unbiased regardless; normality only buys
        # exact small-sample inference, which n has already made unnecessary.
        detail += (
            f"residuals depart from normality, but at n = {n} the coefficient "
            f"intervals are approximately valid anyway"
        )
    else:
        detail += (
            f"residuals depart from normality at n = {n}, so the intervals and p-values "
            f"are approximate at best"
        )
    return Assumption(name, passed, detail, float(statistic), float(jb_p))


def influence_assumption(fit: Any, n: int) -> Assumption:
    """How much of the sample exceeds the conventional Cook's distance cutoff."""
    name = "Influential observations (Cook's distance)"
    try:
        distances = np.asarray(OLSInfluence(fit).cooks_distance[0], dtype=float)
    except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - degenerate design
        return Assumption(name, None, "Cook's distance could not be computed")
    finite = distances[np.isfinite(distances)]
    if finite.size == 0 or n <= 0:  # pragma: no cover - guarded upstream
        return Assumption(name, None, "Cook's distance could not be computed")

    cutoff = INFLUENCE_CUTOFF_MULTIPLE / n
    share = float(np.mean(finite > cutoff))
    passed = share <= INFLUENCE_SHARE_LIMIT
    detail = (
        f"{share:.1%} of rows exceed the 4/n cutoff ({cutoff:.4g}); largest Cook's "
        f"distance {float(finite.max()):.4g}"
    )
    detail += (
        ". The rule flags roughly 5% of well-behaved data, so this is unremarkable"
        if passed
        else (
            f". Above {INFLUENCE_SHARE_LIMIT:.0%}, so the fit leans on a minority of rows; "
            f"check them before reading the coefficients"
        )
    )
    return Assumption(name, passed, detail, share)


def dispersion_assumption(pearson_chi_square: float, df_resid: float, *, family: str) -> Assumption:
    """Pearson chi-square over residual degrees of freedom.

    A correctly specified Poisson has a ratio near 1 because its variance is
    its mean. A ratio well above 1 means the standard errors are too small —
    the coefficients stay roughly right while every p-value beside them is
    optimistic. The verdict comes from the formal upper-tail chi-square test
    rather than from eyeballing the ratio, so it scales with the sample.
    """
    name = "Overdispersion (Pearson chi²/df)"
    if df_resid <= 0 or not math.isfinite(pearson_chi_square):  # pragma: no cover
        return Assumption(name, None, "no residual degrees of freedom to evaluate dispersion")

    ratio = float(pearson_chi_square) / float(df_resid)
    tail = float(stats.chi2.sf(float(pearson_chi_square), int(df_resid)))
    overdispersed = ratio > 1.0 and tail < ALPHA
    detail = f"Pearson chi² = {pearson_chi_square:.6g} on {int(df_resid)} df, ratio {ratio:.4g}"
    if not overdispersed:
        detail += f"; consistent with the {family} variance assumption (upper-tail p = {tail:.4g})"
    elif family == "poisson":
        detail += (
            f"; the variance exceeds the mean (upper-tail p = {tail:.4g}), so Poisson "
            f"standard errors are too small. Re-run with family=negative_binomial."
        )
    else:
        detail += (
            f"; the spread still exceeds what the fitted negative binomial allows "
            f"(upper-tail p = {tail:.4g}), so the standard errors remain optimistic"
        )
    return Assumption(name, not overdispersed, detail, ratio, p_value(tail))


# Below this many observations in the rarer outcome class per estimated
# coefficient, a logistic regression's coefficients are biased away from zero
# and its intervals are too narrow. Ten is the long-standing rule of thumb.
MIN_EVENTS_PER_PREDICTOR = 10.0


def events_per_predictor_assumption(successes: int, failures: int, terms: int) -> Assumption:
    """Whether a logit has enough of its rarer outcome to support its coefficients.

    A logit is limited by the smaller of the two outcome classes, not by n: a
    thousand rows carrying four failures estimate as badly as a sample of eight.
    """
    name = "Events per predictor"
    if terms <= 0:  # pragma: no cover - a regressor is always required
        return Assumption(name, None, "no estimated coefficient to evaluate")

    rarer = min(int(successes), int(failures))
    ratio = rarer / terms
    passed = ratio >= MIN_EVENTS_PER_PREDICTOR
    detail = (
        f"{rarer} observation(s) in the rarer outcome class across {terms} estimated "
        f"coefficient(s): {ratio:.4g} per predictor"
    )
    detail += (
        f"; at or above the conventional {MIN_EVENTS_PER_PREDICTOR:.0f}"
        if passed
        else (
            f"; below {MIN_EVENTS_PER_PREDICTOR:.0f}, so the coefficients are biased away "
            f"from zero and the intervals are too narrow"
        )
    )
    return Assumption(name, passed, detail, float(ratio))
