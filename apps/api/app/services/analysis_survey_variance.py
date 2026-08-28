"""The sampling design behind a Tier 6 estimate: building it, checking it, using it.

Split out of :mod:`app.services.analysis_survey` so the arithmetic that decides
whether a reported standard error is right can be read on its own, against a
textbook, without the operation plumbing in the way. Every formula used is
written above the function that implements it.

Three things live here: the design object and the rules for constructing a
valid one from a dataframe (which rows are usable, which weights are usable,
and what to warn about); the variance estimators; and the design correction for
a chi-square test of independence, which is built out of those variances.

The estimator throughout is **Taylor linearization with the ultimate-cluster
approximation**, which is the standard design-based variance for a stratified
multistage sample and the one R's ``survey`` package and Stata's ``svy`` use by
default. Nothing here is an approximation invented for this codebase.

Notation. For unit *i*: :math:`w_i` is the design weight, :math:`y_i` the
analysis variable, :math:`h` indexes strata and :math:`(h,i)` primary sampling
units (PSUs). :math:`\\hat W = \\sum_i w_i` is the estimated population size.

**1. Variance of an estimated total.** For a total of per-unit contributions
:math:`u_i`,

.. math::

    \\hat V\\!\\left(\\sum_i u_i\\right)
      = \\sum_h (1 - f)\\,\\frac{n_h}{n_h - 1}
        \\sum_{i=1}^{n_h} \\left(u_{hi} - \\bar u_h\\right)^2

where :math:`u_{hi}` is the PSU total of the contributions, :math:`n_h` the
number of PSUs in stratum *h*, and *f* the sampling fraction. With no strata
and no clusters this collapses to :math:`\\frac{n}{n-1}\\sum_i (u_i - \\bar
u)^2`, i.e. :math:`n` times the sample variance of the contributions.

**2. Weighted total.** :math:`\\hat T = \\sum_i w_i y_i`, with contributions
:math:`u_i = w_i y_i` fed to (1).

**3. Weighted mean.** The weighted mean is a *ratio* of two estimated totals,
:math:`\\hat{\\bar y} = \\hat T / \\hat W`, so its variance comes from the
first-order Taylor expansion of that ratio: contributions

.. math::

    z_i = \\frac{w_i\\,(y_i - \\hat{\\bar y})}{\\hat W}

fed to (1). Under equal weights, no strata and no clusters this reduces
algebraically to :math:`s^2/n` — the ordinary standard error of a mean — which
is the invariant the tests pin.

**4. Domains (subpopulations, and every group of a ``group_by``).** The domain
mean uses a domain indicator :math:`\\delta_i` rather than a filtered dataset:

.. math::

    \\hat{\\bar y}_d = \\frac{\\sum_i w_i \\delta_i y_i}{\\sum_i w_i \\delta_i},
    \\qquad
    z_i = \\frac{w_i \\delta_i (y_i - \\hat{\\bar y}_d)}{\\hat W_d}

with the sum in (1) running over the **whole sample**, out-of-domain units
contributing zero but still counting toward :math:`n_h`. Deleting them instead
changes the PSU counts, the stratum means and the degrees of freedom, which is
why filter-then-analyze gives the wrong standard error.

**5. Degrees of freedom.** :math:`df = (\\text{number of PSUs}) -
(\\text{number of strata})`, which is exactly :math:`n - 1` when neither is
declared. Confidence intervals use :math:`t_{df,\\,0.975}`.

**6. SRS reference variance, for design effects.** Design effects compare the
design variance to what simple random sampling of the same *n* would have
given. The reference uses weights normalized to sum to *n*, :math:`\\tilde w_i
= n w_i / \\sum_j w_j`, so that it is invariant to the scale of the weights:

.. math::

    \\hat V_{SRS}(\\hat{\\bar y}) = \\frac{\\hat S^2}{n},
    \\qquad
    \\hat S^2 = \\frac{\\sum_i \\tilde w_i (y_i - \\hat{\\bar y})^2}{n - 1}

Under equal weights :math:`\\hat S^2 = s^2` exactly, so DEFF is exactly 1.

**7. Kish's design effect**, the weights-only approximation:

.. math::

    \\text{DEFF}_{\\text{Kish}} = \\frac{n \\sum_i w_i^2}{\\left(\\sum_i
    w_i\\right)^2} = 1 + CV_w^2

with :math:`CV_w` the coefficient of variation of the weights (population sd).
The design-based ratio in (6) coincides with Kish's exactly when the squared
residuals :math:`(y_i - \\hat{\\bar y})^2` are constant across units — which is
the homoscedasticity assumption behind Kish's approximation — and diverges from
it otherwise, which is why both are reported.

**8. Rao-Scott first-order correction**, for a test of independence in an
:math:`r \\times c` table (Rao & Scott 1984). Pearson's statistic on
survey-weighted proportions is not chi-square distributed; it is a weighted sum
of chi-squares whose weights are the generalized design effects. Dividing by
their mean,

.. math::

    \\hat\\delta = \\frac{\\sum_{ij}(1 - \\hat p_{ij})\\hat d_{ij}
        - \\sum_i (1 - \\hat p_{i+})\\hat d_{i+}
        - \\sum_j (1 - \\hat p_{+j})\\hat d_{+j}}{(r-1)(c-1)}

with :math:`\\hat d` the design effect (6) of the corresponding estimated
proportion, restores an approximate :math:`\\chi^2_{(r-1)(c-1)}` reference
distribution. Under equal weights every :math:`\\hat d` is 1 and the numerator
is exactly :math:`(r-1)(c-1)`, so :math:`\\hat\\delta = 1` and nothing is
corrected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analysis_prep import numeric_series
from app.services.analysis_result import ExecutionError
from app.services.analysis_stats import CONFIDENCE_LEVEL, Assumption

# A variance needs at least two PSUs per stratum; below that the estimator is
# 0/0 rather than small.
MIN_PSU_PER_STRATUM = 2


@dataclass(frozen=True)
class SurveyDesign:
    """The sampling design an estimate is computed under.

    Immutable: :func:`restrict` returns a new design rather than editing this
    one, so the "what would filter-then-analyze have given" comparison cannot
    corrupt the design the correct estimate is using.
    """

    weights: np.ndarray
    strata: np.ndarray | None = None
    clusters: np.ndarray | None = None
    fpc: float | None = None
    weights_column: str = ""
    strata_column: str | None = None
    cluster_column: str | None = None

    @property
    def n(self) -> int:
        return int(self.weights.size)

    @property
    def sum_weights(self) -> float:
        return float(self.weights.sum())

    @property
    def n_strata(self) -> int:
        return 1 if self.strata is None else int(pd.unique(self.strata).size)

    @property
    def n_psu(self) -> int:
        if self.clusters is None:
            return self.n
        frame = pd.DataFrame({"stratum": self._stratum_labels(), "psu": self.clusters})
        return int(len(frame.drop_duplicates()))

    @property
    def dof(self) -> float:
        """PSUs minus strata — which is n - 1 when neither was declared."""
        return float(self.n_psu - self.n_strata)

    @property
    def dof_basis(self) -> str:
        if self.clusters is None and self.strata is None:
            return "n - 1 (no clustering or stratification declared)"
        return (
            f"PSUs minus strata: {self.n_psu} primary sampling unit(s) in "
            f"{self.n_strata} stratum/strata"
        )

    def _stratum_labels(self) -> np.ndarray:
        return np.zeros(self.n, dtype=np.int8) if self.strata is None else self.strata

    def describe(self) -> dict[str, Any]:
        """What the estimate assumed, for the narrator and the methods note."""
        return {
            "weights": self.weights_column,
            "strata": self.strata_column,
            "cluster": self.cluster_column,
            "sampling_fraction": self.fpc,
            "variance_estimator": (
                "Taylor linearization, ultimate-cluster (first-stage) approximation"
            ),
            "n": self.n,
            "n_psu": self.n_psu,
            "n_strata": self.n_strata,
            "degrees_of_freedom": self.dof,
        }

    def validate(self) -> None:
        """Refuse a design whose variance is undefined before computing anything.

        Raised at build time rather than from inside a variance sum, so the
        message is about the design rather than about whichever statistic
        happened to be computed first.
        """
        if self.n < MIN_PSU_PER_STRATUM:
            raise ExecutionError(
                f"only {self.n} usable row(s) after dropping missing values; "
                f"a standard error needs at least {MIN_PSU_PER_STRATUM}"
            )
        counts = self._psu_counts()
        singletons = [str(label) for label, count in counts.items() if count < MIN_PSU_PER_STRATUM]
        if singletons:
            unit = "PSU" if self.clusters is not None else "respondent"
            raise ExecutionError(
                f"stratum/strata {singletons[:5]} contain 1 {unit} each; a design-based "
                f"variance needs at least {MIN_PSU_PER_STRATUM} per stratum. Collapse the "
                f"single-{unit} strata into a neighbouring one, or drop the strata parameter."
            )

    def _psu_counts(self) -> dict[Any, int]:
        frame = pd.DataFrame(
            {
                "stratum": self._stratum_labels(),
                "psu": np.arange(self.n) if self.clusters is None else self.clusters,
            }
        )
        distinct = frame.drop_duplicates()
        return {key: int(size) for key, size in distinct.groupby("stratum").size().items()}


def restrict(design: SurveyDesign, mask: np.ndarray) -> SurveyDesign:
    """The design as filter-then-analyze would see it — the *wrong* one, on purpose.

    Used only to compute the naive comparison in ``subpopulation_estimate``:
    dropping the out-of-domain rows shrinks the PSU counts and the degrees of
    freedom, and that is precisely the difference the operation exists to show.
    """
    return replace(
        design,
        weights=design.weights[mask],
        strata=None if design.strata is None else design.strata[mask],
        clusters=None if design.clusters is None else design.clusters[mask],
    )


def linearized_variance(design: SurveyDesign, contributions: np.ndarray) -> float:
    """Formula (1): ultimate-cluster variance of a total of *contributions*."""
    frame = pd.DataFrame(
        {
            "stratum": design._stratum_labels(),
            "psu": np.arange(design.n) if design.clusters is None else design.clusters,
            "u": contributions,
        }
    )
    psu_totals = frame.groupby(["stratum", "psu"], sort=False, observed=True)["u"].sum()
    correction = 1.0 if design.fpc is None else 1.0 - float(design.fpc)

    variance = 0.0
    for _, block in psu_totals.groupby(level="stratum", sort=False, observed=True):
        values = block.to_numpy(dtype=float)
        size = values.size
        if size < MIN_PSU_PER_STRATUM:  # pragma: no cover - caught by validate()
            raise ExecutionError("a stratum with one PSU has no estimable variance")
        deviations = values - values.mean()
        variance += correction * size / (size - 1) * float((deviations**2).sum())
    return variance


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Estimate:
    """One design-based estimate, with everything needed to report it honestly."""

    value: float
    standard_error: float
    ci_low: float
    ci_high: float
    dof: float
    n: int
    sum_weights: float
    unweighted: float

    @property
    def coefficient_of_variation(self) -> float:
        """Relative standard error — the usual publication threshold for "too noisy"."""
        if self.value == 0 or not math.isfinite(self.value):
            return math.nan
        return abs(self.standard_error / self.value)


def _with_interval(
    value: float,
    variance: float,
    design: SurveyDesign,
    *,
    n: int,
    sum_weights: float,
    unweighted: float,
) -> Estimate:
    """Attach a t interval on the design degrees of freedom — formula (5)."""
    standard_error = math.sqrt(variance) if variance > 0 else 0.0
    dof = design.dof
    if dof <= 0 or not math.isfinite(standard_error):  # pragma: no cover - validate() guards
        return Estimate(value, math.nan, math.nan, math.nan, dof, n, sum_weights, unweighted)
    margin = float(stats.t.ppf(1 - (1 - CONFIDENCE_LEVEL) / 2, dof)) * standard_error
    return Estimate(
        value, standard_error, value - margin, value + margin, dof, n, sum_weights, unweighted
    )


def _domain(design: SurveyDesign, domain: np.ndarray | None) -> np.ndarray:
    return np.ones(design.n, dtype=float) if domain is None else domain.astype(float)


def weighted_mean(
    design: SurveyDesign, values: np.ndarray, domain: np.ndarray | None = None
) -> Estimate:
    """Formulas (3) and (4): the weighted mean and its linearized variance."""
    indicator = _domain(design, domain)
    weights = design.weights * indicator
    total_weight = float(weights.sum())
    if total_weight <= 0:
        raise ExecutionError("no positive weights remain for this estimate")

    mean = float((weights * values).sum() / total_weight)
    contributions = weights * (values - mean) / total_weight
    variance = linearized_variance(design, contributions)

    inside = indicator > 0
    return _with_interval(
        mean,
        variance,
        design,
        n=int(inside.sum()),
        sum_weights=total_weight,
        unweighted=float(np.mean(values[inside])) if inside.any() else math.nan,
    )


def weighted_total(
    design: SurveyDesign, values: np.ndarray, domain: np.ndarray | None = None
) -> Estimate:
    """Formula (2): the estimated population total and its linearized variance."""
    indicator = _domain(design, domain)
    weights = design.weights * indicator
    contributions = weights * values
    variance = linearized_variance(design, contributions)

    inside = indicator > 0
    return _with_interval(
        float(contributions.sum()),
        variance,
        design,
        n=int(inside.sum()),
        sum_weights=float(weights.sum()),
        unweighted=float(np.sum(values[inside])) if inside.any() else math.nan,
    )


def srs_mean_variance(
    design: SurveyDesign, values: np.ndarray, domain: np.ndarray | None = None
) -> float:
    """Formula (6): what simple random sampling of the same n would have given."""
    indicator = _domain(design, domain)
    inside = indicator > 0
    n = int(inside.sum())
    if n < 2:
        return math.nan

    weights = design.weights[inside]
    inside_values = values[inside]
    mean = float((weights * inside_values).sum() / weights.sum())
    normalized = n * weights / weights.sum()
    element_variance = float((normalized * (inside_values - mean) ** 2).sum() / (n - 1))
    return element_variance / n


def design_effect(
    design: SurveyDesign, values: np.ndarray, domain: np.ndarray | None = None
) -> float:
    """The design-based DEFF: design variance over the SRS reference of formula (6)."""
    reference = srs_mean_variance(design, values, domain)
    if not math.isfinite(reference) or reference <= 0:
        return math.nan
    return weighted_mean(design, values, domain).standard_error ** 2 / reference


# ---------------------------------------------------------------------------
# Weights-only diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeightProfile:
    """What the weights alone say about how much precision they cost."""

    n: int
    sum_weights: float
    minimum: float
    maximum: float
    cv: float
    ratio: float
    deff: float
    effective_n: float


def profile_weights(weights: np.ndarray) -> WeightProfile:
    """Formula (7): Kish's design effect and the effective sample size."""
    n = int(weights.size)
    total = float(weights.sum())
    sum_squares = float((weights**2).sum())
    deff = n * sum_squares / total**2 if total > 0 else math.nan
    mean = float(weights.mean())
    # Population sd (ddof=0) is the one for which DEFF = 1 + CV^2 holds exactly.
    cv = float(weights.std(ddof=0) / mean) if mean > 0 else math.nan
    minimum, maximum = float(weights.min()), float(weights.max())
    return WeightProfile(
        n=n,
        sum_weights=total,
        minimum=minimum,
        maximum=maximum,
        cv=cv,
        ratio=maximum / minimum if minimum > 0 else math.inf,
        deff=deff,
        effective_n=n / deff if deff and math.isfinite(deff) and deff > 0 else math.nan,
    )


# Below this many respondents, a weighted estimate projected onto a population
# is not something this product should print without saying so. 30 is the
# conventional publication floor for a survey subgroup estimate; it is a
# convention, and the check says so rather than implying a law.
MIN_DOMAIN_N = 30

# Weight-distribution alarms. A CV of 1 means Kish's design effect is 2 — the
# weighting has thrown away more than half the sample — and a max/min ratio
# past 50 means a handful of respondents carry the estimate whatever the CV
# says. Either one is worth interrupting the narrator for.
MAX_WEIGHT_CV = 1.0
MAX_WEIGHT_RATIO = 50.0

_CALIBRATION_NOTE = (
    "The weights are treated as fixed. If they were produced by "
    "post-stratification, raking or calibration, their own sampling variability "
    "is not in these standard errors."
)


# ---------------------------------------------------------------------------
# Preparation: one definition of "the usable rows and the design over them"
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SurveyData:
    """The rows an operation may use, the design over them, and what was lost."""

    frame: pd.DataFrame
    design: SurveyDesign
    n_excluded: int
    notes: list[str]
    checks: list[Assumption]


def _weight_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Coerce the weight column, refusing the values that make weighting a lie."""
    weights = numeric_series(df, column)
    negative = int((weights < 0).sum())
    if negative:
        smallest = float(weights.min())
        raise ExecutionError(
            f"{negative} row(s) have a negative value in the weight column {column!r} "
            f"(smallest {smallest:g}). A negative design weight has no interpretation — "
            f"check that {column!r} is a weight and not a score or a difference."
        )
    return weights


def _label_column(df: pd.DataFrame, column: str | None) -> pd.Series | None:
    return None if column is None else df[column].astype("object")


def prepare_survey_data(
    df: pd.DataFrame,
    params: dict[str, Any],
    *,
    numeric_columns: tuple[str, ...],
    label_columns: tuple[str, ...] = (),
) -> SurveyData:
    """Drop rows the estimate cannot use, then build the design over the rest.

    Listwise: a row missing the analysis variable, the weight, or any design or
    grouping label is unusable, because there is nowhere to put it. The count
    and the reason travel with the result.
    """
    weights_column = params["weights"]
    strata_column = params.get("strata")
    cluster_column = params.get("cluster")

    columns: dict[str, pd.Series] = {name: numeric_series(df, name) for name in numeric_columns}
    for name in label_columns:
        if name not in df.columns:
            raise ExecutionError(f"column {name!r} is not in the dataset")
        columns[name] = _label_column(df, name)
    columns[weights_column] = _weight_series(df, weights_column)
    for name in (strata_column, cluster_column):
        if name is not None:
            columns[name] = _label_column(df, name)

    working = pd.DataFrame(columns)
    missing_weight = int(working[weights_column].isna().sum())
    complete = working.dropna()
    dropped_missing = len(df) - len(complete)

    zero_weight = int((complete[weights_column] == 0).sum())
    usable = complete[complete[weights_column] > 0].reset_index(drop=True)
    if usable.empty:
        raise ExecutionError(
            f"no positive weights remain in {weights_column!r} after dropping rows missing "
            f"{list(numeric_columns) + list(label_columns)} or the weight "
            f"({dropped_missing} row(s) incomplete, {zero_weight} with a zero weight)"
        )

    design = SurveyDesign(
        weights=usable[weights_column].to_numpy(dtype=float),
        strata=None if strata_column is None else usable[strata_column].to_numpy(),
        clusters=None if cluster_column is None else usable[cluster_column].to_numpy(),
        fpc=None if params.get("fpc") is None else float(params["fpc"]),
        weights_column=str(weights_column),
        strata_column=strata_column,
        cluster_column=cluster_column,
    )
    design.validate()

    return SurveyData(
        frame=usable,
        design=design,
        n_excluded=dropped_missing + zero_weight,
        notes=_exclusion_notes(dropped_missing, zero_weight, weights_column),
        checks=[
            _weight_variation_check(design.weights),
            _weight_completeness_check(missing_weight, len(usable)),
            _design_check(design),
        ],
    )


def _exclusion_notes(dropped: int, zero_weight: int, weights_column: str) -> list[str]:
    notes: list[str] = []
    if dropped:
        notes.append(
            f"Excluded {dropped} row(s) missing the analysis variable, the weight, or a "
            f"design label. Dropping cases whose weight is missing can bias the estimate: "
            f"they leave the population being described, and the remaining weights are not "
            f"recalibrated to stand in for them."
        )
    if zero_weight:
        notes.append(
            f"Dropped {zero_weight} row(s) with a zero weight in {weights_column!r} — a zero "
            f"weight removes the respondent from the estimated population entirely."
        )
    return notes


def _weight_variation_check(weights: np.ndarray) -> Assumption:
    """Extreme weights make every estimate unstable; say so with the numbers."""
    profile = profile_weights(weights)
    name = "Weight variation"
    if not math.isfinite(profile.cv):  # pragma: no cover - guarded by _prepare
        return Assumption(name, None, "the weights have no usable mean")

    spread = (
        f"weights run from {profile.minimum:.4g} to {profile.maximum:.4g} "
        f"(ratio {profile.ratio:.4g}), CV = {profile.cv:.4g}, "
        f"Kish design effect {profile.deff:.4g}"
    )
    passed = profile.cv <= MAX_WEIGHT_CV and profile.ratio <= MAX_WEIGHT_RATIO
    if passed:
        return Assumption(name, True, f"{spread}; weighting costs little precision", profile.cv)
    return Assumption(
        name,
        False,
        f"{spread}. Past a CV of {MAX_WEIGHT_CV:g} or a ratio of {MAX_WEIGHT_RATIO:g} a "
        f"handful of respondents carry the estimate, so it moves a lot if any of them "
        f"is unusual. Effective sample size is {profile.effective_n:.4g}, not {profile.n}.",
        profile.cv,
    )


def _weight_completeness_check(missing: int, used: int) -> Assumption:
    """Reported three-valued: dropping is correct, whether it biases is unknowable here."""
    name = "Weight completeness"
    if missing == 0:
        return Assumption(name, True, f"every one of the {used} usable row(s) carries a weight")
    return Assumption(
        name,
        None,
        f"{missing} row(s) had no weight and were dropped, leaving {used}. That biases the "
        f"estimate if those respondents differ from the ones who were weighted — which this "
        f"check cannot determine.",
    )


def _design_check(design: SurveyDesign) -> Assumption:
    """State the design that was assumed, since silence here reads as certainty."""
    declared = [
        f"weights = {design.weights_column!r}",
        f"strata = {design.strata_column!r}" if design.strata_column else "no strata",
        f"cluster = {design.cluster_column!r}" if design.cluster_column else "no cluster",
        f"sampling fraction = {design.fpc:g}" if design.fpc is not None else "no fpc",
    ]
    caveats = []
    if design.cluster_column is None:
        caveats.append(
            "with no cluster column declared, respondents are treated as sampled "
            "independently; if the survey sampled clusters (households, schools, "
            "interviewer areas), the real standard error is larger than this one"
        )
    if design.strata_column is None:
        caveats.append(
            "with no strata declared, no credit is taken for stratification, so the "
            "standard error is conservative if the sample was in fact stratified"
        )
    caveats.append(_CALIBRATION_NOTE)
    return Assumption("Design specification", None, f"{'; '.join(declared)}. " + " ".join(caveats))


def sample_size_check(counts: dict[str, int]) -> Assumption:
    """Loud about small domains.

    Deliberately not :func:`check_group_sizes`: its threshold is 5 and its
    verdict is "fragile", which is the right sentence for a t-test and the
    wrong one for a number that is about to be multiplied by a population.
    """
    name = "Sample size for a weighted estimate"
    if not counts:  # pragma: no cover - callers always pass at least one domain
        return Assumption(name, None, "no domains")
    smallest_label = min(counts, key=lambda key: counts[key])
    smallest = counts[smallest_label]
    if smallest >= MIN_DOMAIN_N:
        return Assumption(
            name,
            True,
            f"the smallest domain ({smallest_label}) has {smallest} respondents",
            float(smallest),
        )
    return Assumption(
        name,
        False,
        f"the smallest domain ({smallest_label}) has only {smallest} respondent(s), below the "
        f"conventional floor of {MIN_DOMAIN_N} for reporting a weighted estimate. Projecting "
        f"{smallest} respondents onto a population produces a number with a very wide "
        f"interval, whatever the point estimate looks like.",
        float(smallest),
    )


def small_domain_notes(counts: dict[str, int], sum_weights: dict[str, float]) -> list[str]:
    return [
        f"Only {count} respondent(s) in {label}, standing for an estimated "
        f"{sum_weights.get(label, float('nan')):,.0f} people. Read that estimate as an "
        f"indication, not a measurement."
        for label, count in sorted(counts.items())
        if count < MIN_DOMAIN_N
    ]


# ---------------------------------------------------------------------------
# Design-corrected test statistics
# ---------------------------------------------------------------------------


def _cell_design_effect(data: SurveyData, indicator: np.ndarray) -> float:
    """DEFF of an estimated proportion — the building block of the correction."""
    return design_effect(data.design, indicator.astype(float))


def rao_scott_factor(
    data: SurveyData, rows: pd.Series, columns: pd.Series, proportions: np.ndarray
) -> float:
    """First-order Rao-Scott correction factor.

    Rao & Scott (1984): the Pearson statistic computed on survey-weighted
    proportions is distributed as a weighted sum of chi-squares whose weights
    are the generalized design effects. The first-order correction divides by
    their mean,

        delta = [ sum_ij (1 - p_ij) d_ij
                  - sum_i (1 - p_i+) d_i+
                  - sum_j (1 - p_+j) d_+j ] / ((r-1)(c-1))

    where d is the design effect of the corresponding estimated proportion.
    Under equal weights and no clustering every d is 1 and the bracket is
    exactly (r-1)(c-1), so delta is exactly 1 and nothing is corrected — which
    is the property the tests pin.

    This is the first-order correction only. The second-order (Rao-Scott F,
    Satterthwaite) version needs the full covariance of the cell proportions;
    it is not implemented, and the result says which one it used.
    """
    row_labels = sorted(rows.unique())
    column_labels = sorted(columns.unique())
    r, c = len(row_labels), len(column_labels)

    cell_deff = np.array(
        [
            [
                _cell_design_effect(data, ((rows == r_label) & (columns == c_label)).to_numpy())
                for c_label in column_labels
            ]
            for r_label in row_labels
        ]
    )
    row_deff = np.array(
        [_cell_design_effect(data, (rows == label).to_numpy()) for label in row_labels]
    )
    column_deff = np.array(
        [_cell_design_effect(data, (columns == label).to_numpy()) for label in column_labels]
    )

    row_margin = proportions.sum(axis=1)
    column_margin = proportions.sum(axis=0)
    bracket = (
        float(((1 - proportions) * cell_deff).sum())
        - float(((1 - row_margin) * row_deff).sum())
        - float(((1 - column_margin) * column_deff).sum())
    )
    return bracket / ((r - 1) * (c - 1))


def pearson_statistic(proportions: np.ndarray, scale: float) -> float:
    """Pearson's X^2 for a table of proportions scaled to *scale* observations."""
    expected = np.outer(proportions.sum(axis=1), proportions.sum(axis=0))
    return float(scale * (((proportions - expected) ** 2) / expected).sum())
