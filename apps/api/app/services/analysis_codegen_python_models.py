"""Python source for the modelled tiers: regression, time series, survey.

:mod:`app.services.analysis_codegen_python` emits Tiers 1 to 3, which need
nothing beyond pandas, numpy and scipy. Everything here needs statsmodels, and
everything here is a model rather than a summary — which changes what a faithful
export has to carry.

A descriptive statistic is reproduced by writing down the same arithmetic. A
model is not: a coefficient depends on which rows survived listwise deletion,
which level of a categorical regressor became the baseline, which covariance
estimator was asked for, which grid a series was resampled onto and which of its
periods were interpolated rather than measured. Change any one of those and the
number changes while the code still looks right. So the emitted blocks reproduce
those choices explicitly — ``regression_design`` codes categoricals against the
alphabetically first level exactly as the product does, ``series_grid`` rebuilds
the same regular grid and reports how much of it was filled in — rather than
handing the reader a tidier script that answers a slightly different question.

Registration goes through :func:`app.services.analysis_codegen_python.register`,
so the façade in :mod:`app.services.analysis_codegen` picks these up with no
special case: an operation with an emitter is exported, and one without is
marked as a gap.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.services.analysis_codegen_python import (
    ALPHA,
    CONFIDENCE_LEVEL,
    DATA,
    Lines,
    py_literal,
    register,
    register_helper,
)

# Mirrors analysis_regression_core.INTERCEPT and P_VALUE_FLOOR, analysis_
# regression.LOGISTIC_TO_COHEN_D / QUANTREG_MAX_ITER / DEFAULT_TAU, the tier-5
# caps in analysis_timeseries, and the tier-6 confidence level. A test asserts
# none of them have drifted, because a different constant is a different number.
INTERCEPT = "(Intercept)"
P_VALUE_FLOOR = 2.2250738585072014e-308  # sys.float_info.min
LOGISTIC_TO_COHEN_D = 0.5513288954217921  # sqrt(3) / pi
QUANTREG_MAX_ITER = 10_000
DEFAULT_TAU = 0.5

MACKINNON_P_FLOOR = 1e-10
COEFFICIENT_P_FLOOR = ALPHA / 1e8
LJUNG_BOX_P_FLOOR = ALPHA / 1e6
STL_MIN_CYCLES = 3
STL_SEASONAL_CYCLES = 2
MAX_LAG_FRACTION = 0.25
MAX_LAGS = 60
MAX_DIFFERENCES = 2
MIN_RESIDUAL_PERIODS = 10
FORECAST_CONTEXT_MULTIPLE = 3
MAX_FORECAST_CONTEXT = 60
SEASONAL_PERIODS = {"D": 7, "W": 52, "ME": 12, "QE": 4}

# Column names for the exponentiated view of a coefficient, as the product
# spells them: exp(beta) is an odds ratio in a logit and a rate ratio in a
# count model, and calling both "ratio" would lose that distinction.
ODDS_RATIO = ("odds_ratio", "or_ci_low", "or_ci_high")
RATE_RATIO = ("irr", "irr_ci_low", "irr_ci_high")


def _statsmodels_version() -> str:
    try:
        return version("statsmodels")
    except PackageNotFoundError:  # pragma: no cover - statsmodels is a hard dependency
        return "?"


# ---------------------------------------------------------------------------
# Imports the emitted blocks need beyond pandas, numpy and scipy
# ---------------------------------------------------------------------------
#
# Two of these are comments rather than imports, and travel with the imports for
# the same reason: a fit is only reproducible against the library that computed
# it, and the result-object API the tsa blocks use does not exist in an older
# statsmodels, where the call raises rather than returning something wrong.

_SM_NOTE = f"# Fitted with statsmodels {_statsmodels_version()} — the version the product used."
_RESULT_OBJECT_NOTE = "# The result_object=True arguments below need statsmodels 0.15 or newer."

_SM = "import statsmodels.api as sm"
_OLS = "from statsmodels.regression.linear_model import OLS"
_QUANTREG = "from statsmodels.regression.quantile_regression import QuantReg"
_LJUNGBOX = "from statsmodels.stats.diagnostic import acorr_ljungbox"
_BREUSCH_PAGAN = "from statsmodels.stats.diagnostic import het_breuschpagan"
_VIF = "from statsmodels.stats.outliers_influence import variance_inflation_factor"
_DURBIN_WATSON = "from statsmodels.stats.stattools import durbin_watson"
_JARQUE_BERA = "from statsmodels.stats.stattools import jarque_bera"
_ARIMA = "from statsmodels.tsa.arima.model import ARIMA"
_STL = "from statsmodels.tsa.seasonal import STL"
_CLASSICAL = "from statsmodels.tsa.seasonal import seasonal_decompose"
_ACF = "from statsmodels.tsa.stattools import acf"
_ADFULLER = "from statsmodels.tsa.stattools import adfuller"
_GRANGER = "from statsmodels.tsa.stattools import grangercausalitytests"
_KPSS = "from statsmodels.tsa.stattools import kpss"
_PACF = "from statsmodels.tsa.stattools import pacf"


# ---------------------------------------------------------------------------
# Helpers emitted into the script
# ---------------------------------------------------------------------------

FLOORED_P = register_helper(
    "floored_p",
    f'''def floored_p(value):
    """A p-value that can never print as exactly zero.

    A p-value that underflows to 0.0 is not zero; it is smaller than a double
    can represent, and printing it as 0 claims a certainty no test supports.
    """
    as_float = float(value)
    return max(as_float, {py_literal(P_VALUE_FLOOR)}) if math.isfinite(as_float) else None''',
)

REGRESSION_DESIGN = register_helper(
    "regression_design",
    f'''def regression_design(frame, outcome, regressors, also_required=(), numeric_outcome=True):
    """The rows and columns the model was actually fitted on.

    Two choices here decide every coefficient below. Rows missing the outcome or
    any regressor are dropped listwise and nothing is imputed. A categorical
    regressor is coded against its alphabetically FIRST level, so the baseline
    is a property of the data rather than of row order in the upload; each
    indicator coefficient is the difference from that baseline.
    """
    names = list(dict.fromkeys([outcome, *regressors, *also_required]))
    working = frame.loc[:, names].copy()
    if numeric_outcome:
        # A non-numeric value in a numeric outcome is missing data, not a zero.
        working[outcome] = pd.to_numeric(working[outcome], errors="coerce")
    working = working.dropna()

    columns = {{{py_literal(INTERCEPT)}: np.ones(len(working), dtype=float)}}
    references = {{}}
    for name in regressors:
        series = working[name]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            columns[name] = series.to_numpy(dtype=float)
            continue
        as_text = series.astype(str)
        levels = sorted(as_text.unique())
        references[name] = levels[0]
        for level in levels[1:]:
            columns["{{}}[{{}}]".format(name, level)] = (as_text == level).to_numpy(dtype=float)
    return working, pd.DataFrame(columns, index=working.index), references''',
)

COEFFICIENT_TABLE = register_helper(
    "coefficient_table",
    f'''def coefficient_table(fit, statistic, exclude=(), ratio=None):
    """Estimate, standard error, statistic, p-value and {CONFIDENCE_LEVEL:.0%} interval per term.

    *ratio* names three columns for the exponentiated view — an odds ratio in a
    logit, an incidence rate ratio in a count model. exp() is clipped rather
    than allowed to overflow, so a separated term saturates instead of raising.
    """
    bounds = fit.conf_int(alpha={py_literal(round(1 - CONFIDENCE_LEVEL, 10))})
    rows = []
    for term in fit.params.index:
        if term in exclude:
            continue
        low = float(bounds.loc[term].iloc[0])
        high = float(bounds.loc[term].iloc[1])
        coefficient = float(fit.params[term])
        row = {{
            "term": str(term),
            "coefficient": coefficient,
            "std_err": float(fit.bse[term]),
            statistic: float(fit.tvalues[term]),
            "p_value": floored_p(fit.pvalues[term]),
            "ci_low": low,
            "ci_high": high,
        }}
        if ratio is not None:
            for name, value in zip(ratio, (coefficient, low, high)):
                row[name] = float(np.exp(np.clip(value, -709.0, 709.0)))
        rows.append(row)
    return pd.DataFrame(rows)''',
    requires=(FLOORED_P,),
)

VIF_TABLE = register_helper(
    "vif_table",
    '''def vif_table(exog):
    """Variance inflation factor per term: whose coefficient is not separately identified.

    Above 10 the model as a whole can fit well while no individual coefficient
    in the correlated set means anything on its own.
    """
    matrix = exog.to_numpy(dtype=float)
    return pd.DataFrame([
        {"term": str(term), "vif": float(variance_inflation_factor(matrix, position))}
        for position, term in enumerate(exog.columns)
        if position > 0
    ])''',
)

SUCCESS_INDICATOR = register_helper(
    "success_indicator",
    '''def success_indicator(series, success):
    """1 where the outcome equals *success*, comparing as text and then as number.

    Comparing "1" against a float column of 1.0 as text alone would match
    nothing, and a base rate of zero reads as a finding rather than as a
    spelling mistake.
    """
    matched = series.astype(str) == str(success)
    if not bool(matched.any()):
        try:
            matched = pd.to_numeric(series, errors="coerce") == float(success)
        except (TypeError, ValueError):
            pass
    return matched.to_numpy(dtype=float)''',
)

SERIES_GRID = register_helper(
    "series_grid",
    '''def series_grid(frame, date_column, value_columns, freq=None, agg="mean"):
    """The regular grid every time-series operation is fitted on.

    Uploaded data is essentially never regularly spaced, and every method below
    assumes it is. Rows missing the date or any value are dropped, observations
    sharing a period are collapsed by *agg*, and periods with no observation at
    all are filled by time-weighted linear interpolation — a forward fill would
    fabricate a flat stretch and bias every variance and autocorrelation
    downward. The filled points are estimates, not measurements, and the count
    returned here is what the product reports so a reader can discount them.
    """
    working = pd.DataFrame({date_column: pd.to_datetime(frame[date_column], errors="coerce")})
    for name in value_columns:
        working[name] = pd.to_numeric(frame[name], errors="coerce")
    working = working.dropna().sort_values(date_column)

    index = pd.DatetimeIndex(working[date_column])
    freq = infer_series_freq(index) if freq is None else freq
    grid = working.set_index(date_column)[list(value_columns)].resample(freq).agg(agg)
    interpolated = int(grid.isna().to_numpy().any(axis=1).sum())
    filled = grid.interpolate(method="time").ffill().bfill().astype(float)
    return filled, freq, interpolated''',
)

INFER_FREQ = register_helper(
    "infer_series_freq",
    '''def infer_series_freq(index):
    """One of D/W/ME/QE/YE for *index*.

    pandas can name an offset outright when the stamps already fall on a grid,
    which is the strongest evidence available. Otherwise the median gap is
    matched to the nearest nominal period on a LOG scale, so 14 days reads as
    weekly rather than being pulled toward monthly by the wider spacing above it.
    """
    nominal_days = {"D": 1.0, "W": 7.0, "ME": 30.44, "QE": 91.31, "YE": 365.25}
    unique = pd.DatetimeIndex(index.unique()).sort_values()
    alias = pd.infer_freq(unique) if len(unique) >= 3 else None
    head = alias.split("-", 1)[0].upper() if alias else ""
    if head in nominal_days:
        return head
    for prefix, freq in (("W", "W"), ("M", "ME"), ("Q", "QE"), ("Y", "YE"), ("A", "YE")):
        if head.startswith(prefix) and head:
            return freq
    if head in ("D", "B", "C"):
        return "D"

    gaps = np.diff(unique.to_numpy()).astype("timedelta64[s]").astype(float) / 86400.0
    median_days = float(np.median(gaps))
    ordered = sorted(nominal_days.items(), key=lambda item: item[1])
    for (freq, days), (_, next_days) in zip(ordered, ordered[1:]):
        if median_days < math.sqrt(days * next_days):
            return freq
    return ordered[-1][0]''',
)

COMPONENT_STRENGTH = register_helper(
    "component_strength",
    '''def component_strength(residual, component):
    """Wang-Smith-Hyndman strength of a decomposition component, on [0, 1].

    How much of what the component and the noise jointly explain is the
    component rather than the noise. Clipped, because the ratio can exceed one
    when the two are negatively correlated — an artefact, not negative strength.
    """
    combined = np.nanvar(residual + component, ddof=1)
    if not math.isfinite(combined) or combined <= 0:
        return float("nan")
    return float(np.clip(1.0 - np.nanvar(residual, ddof=1) / combined, 0.0, 1.0))''',
)

SLOPE_INTERVAL = register_helper(
    "slope_with_interval",
    '''def slope_with_interval(values, level=__LEVEL__):
    """OLS slope of *values* against its own index, with a t interval."""
    finite = np.isfinite(values)
    y = values[finite]
    x = np.arange(values.size, dtype=float)[finite]
    if y.size < 3:
        return float("nan"), float("nan"), float("nan")
    fit = stats.linregress(x, y)
    margin = float(stats.t.ppf(1 - (1 - level) / 2, y.size - 2)) * float(fit.stderr)
    return float(fit.slope), float(fit.slope) - margin, float(fit.slope) + margin''',
)

LJUNG_BOX = register_helper(
    "ljung_box",
    '''def ljung_box(residual, lags, model_df=0):
    """Joint test that the first *lags* autocorrelations are all zero.

    The lag count is held to a fifth of the series: a Ljung-Box over more lags
    than the sample can support tests mostly noise.
    """
    clean = residual[np.isfinite(residual)]
    dof = max(1, lags - model_df)
    usable = min(lags, max(1, clean.size // 5))
    if clean.size < 8 or usable <= model_df:
        return float("nan"), float("nan"), dof
    table = acorr_ljungbox(clean, lags=[usable], model_df=model_df, return_df=True)
    return (
        float(table["lb_stat"].iloc[0]),
        float(table["lb_pvalue"].iloc[0]),
        max(1, usable - model_df),
    )''',
)

BH_ADJUST = register_helper(
    "bh_adjust",
    '''def bh_adjust(p_values):
    """Benjamini-Hochberg adjusted p-values, in the order given.

    Testing several lags and reporting each at 0.05 is how a series is made to
    look predictive; the step-up procedure adjusts for how many were tested.
    """
    indexed = sorted(
        ((index, float(value)) for index, value in enumerate(p_values) if math.isfinite(value)),
        key=lambda pair: pair[1],
    )
    adjusted = list(p_values)
    m = len(indexed)
    running = 1.0
    for rank in range(m, 0, -1):
        index, p_value = indexed[rank - 1]
        running = min(running, p_value * m / rank)
        adjusted[index] = min(1.0, running)
    return adjusted''',
)

ARIMA_TABLE = register_helper(
    "arima_coefficient_table",
    f'''def arima_coefficient_table(fitted):
    """The fitted ARIMA terms with standard errors, z, p and intervals."""
    bounds = fitted.conf_int(alpha={py_literal(round(1 - CONFIDENCE_LEVEL, 10))})
    rows = []
    for term in fitted.params.index:
        error = float(fitted.bse[term])
        rows.append({{
            "term": str(term),
            "coefficient": float(fitted.params[term]),
            "std_error": error,
            "z": float(fitted.params[term] / error) if error > 0 else float("nan"),
            "p_value": max(float(fitted.pvalues[term]), {py_literal(COEFFICIENT_P_FLOOR)}),
            "ci95_low": float(bounds.loc[term].iloc[0]),
            "ci95_high": float(bounds.loc[term].iloc[1]),
        }})
    return pd.DataFrame(rows)''',
)

SURVEY_DATA = register_helper(
    "survey_data",
    '''def survey_data(frame, weights, numeric_columns=(), label_columns=(), strata=None,
                cluster=None, fpc=None):
    """The rows a weighted estimate may use, and the sampling design over them.

    Listwise: a row missing the analysis variable, the weight or any design or
    grouping label has nowhere to go. A zero weight removes the respondent from
    the estimated population entirely, so those rows go too — and dropping a row
    whose weight is missing biases the estimate, because it leaves the
    population being described and the remaining weights are not recalibrated.
    """
    columns = {name: pd.to_numeric(frame[name], errors="coerce") for name in numeric_columns}
    for name in label_columns:
        columns[name] = frame[name].astype("object")
    columns[weights] = pd.to_numeric(frame[weights], errors="coerce")
    for name in (strata, cluster):
        if name is not None:
            columns[name] = frame[name].astype("object")

    complete = pd.DataFrame(columns).dropna()
    usable = complete[complete[weights] > 0].reset_index(drop=True)
    design = {
        "weights": usable[weights].to_numpy(dtype=float),
        "strata": None if strata is None else usable[strata].to_numpy(),
        "clusters": None if cluster is None else usable[cluster].to_numpy(),
        "fpc": None if fpc is None else float(fpc),
    }
    return usable, design''',
)

SURVEY_VARIANCE = register_helper(
    "survey_variance",
    '''def survey_variance(design, contributions):
    """Ultimate-cluster (Taylor linearization) variance of a total of *contributions*.

        V = sum_h (1 - f) * n_h/(n_h - 1) * sum_i (u_hi - mean(u_h))^2

    over PSU totals u_hi within stratum h. With no strata and no clusters this
    is n times the sample variance of the contributions. This is the estimator
    R's survey package and Stata's svy use by default.
    """
    n = design["weights"].size
    stratum = np.zeros(n, dtype=np.int8) if design["strata"] is None else design["strata"]
    psu = np.arange(n) if design["clusters"] is None else design["clusters"]
    totals = (
        pd.DataFrame({"stratum": stratum, "psu": psu, "u": contributions})
        .groupby(["stratum", "psu"], sort=False, observed=True)["u"]
        .sum()
    )
    correction = 1.0 if design["fpc"] is None else 1.0 - float(design["fpc"])
    variance = 0.0
    for _, block in totals.groupby(level="stratum", sort=False, observed=True):
        values = block.to_numpy(dtype=float)
        deviations = values - values.mean()
        variance += correction * values.size / (values.size - 1) * float((deviations ** 2).sum())
    return variance''',
)

SURVEY_DOF = register_helper(
    "survey_dof",
    '''def survey_dof(design):
    """PSUs minus strata — which is n - 1 when neither was declared."""
    n = design["weights"].size
    if design["clusters"] is None:
        n_psu = n
    else:
        stratum = np.zeros(n, dtype=np.int8) if design["strata"] is None else design["strata"]
        n_psu = len(pd.DataFrame({"s": stratum, "p": design["clusters"]}).drop_duplicates())
    n_strata = 1 if design["strata"] is None else int(pd.unique(design["strata"]).size)
    return float(n_psu - n_strata)''',
)

SURVEY_ESTIMATE = register_helper(
    "survey_estimate",
    '''def survey_estimate(design, values, domain=None, of_total=False, level=__LEVEL__):
    """A weighted mean or total, with its design-based standard error.

    The mean is a RATIO of two estimated totals, so its variance comes from the
    first-order Taylor expansion of that ratio: contributions
    w_i (y_i - mean) / sum(w). The total's contributions are simply w_i y_i.

    A domain is an indicator, not a filter. Out-of-domain units contribute zero
    but still count toward the PSU totals, which is what keeps the strata, the
    PSUs and the degrees of freedom those of the full design. Deleting them
    instead is what makes a filter-then-analyze standard error wrong.
    """
    indicator = np.ones(values.size) if domain is None else np.asarray(domain, dtype=float)
    weights = design["weights"] * indicator
    total_weight = float(weights.sum())
    if of_total:
        value = float((weights * values).sum())
        contributions = weights * values
    else:
        value = float((weights * values).sum() / total_weight)
        contributions = weights * (values - value) / total_weight

    dof = survey_dof(design)
    variance = survey_variance(design, contributions)
    standard_error = math.sqrt(variance) if variance > 0 else 0.0
    margin = float(stats.t.ppf(1 - (1 - level) / 2, dof)) * standard_error
    inside = indicator > 0
    return {
        "value": value,
        "standard_error": standard_error,
        "ci_low": value - margin,
        "ci_high": value + margin,
        "dof": dof,
        "n": int(inside.sum()),
        "sum_weights": total_weight,
        "unweighted": float(np.sum(values[inside]) if of_total else np.mean(values[inside])),
        # Relative standard error: the usual publication threshold for "too noisy".
        "relative_se": abs(standard_error / value) if value != 0 else float("nan"),
    }''',
    requires=(SURVEY_VARIANCE, SURVEY_DOF),
)

SURVEY_DEFF = register_helper(
    "survey_design_effect",
    '''def survey_design_effect(design, values, domain=None):
    """Design variance over what simple random sampling of the same n would give.

    The reference uses weights normalized to sum to n, so it does not depend on
    the scale of the weights. Under equal weights it is exactly 1.
    """
    indicator = np.ones(values.size) if domain is None else np.asarray(domain, dtype=float)
    inside = indicator > 0
    n = int(inside.sum())
    if n < 2:
        return float("nan")
    weights = design["weights"][inside]
    values_in = values[inside]
    mean = float((weights * values_in).sum() / weights.sum())
    normalized = n * weights / weights.sum()
    reference = float((normalized * (values_in - mean) ** 2).sum() / (n - 1)) / n
    if not math.isfinite(reference) or reference <= 0:
        return float("nan")
    return survey_estimate(design, values, indicator)["standard_error"] ** 2 / reference''',
    requires=(SURVEY_ESTIMATE,),
)

WEIGHT_PROFILE = register_helper(
    "weight_profile",
    '''def weight_profile(weights):
    """Kish's design effect and the effective sample size, from the weights alone.

        DEFF_Kish = n * sum(w^2) / (sum w)^2 = 1 + CV^2

    It assumes the weighting is unrelated to the variable being estimated, which
    is why the design-based figure beside it can differ.
    """
    n = int(weights.size)
    total = float(weights.sum())
    deff = n * float((weights ** 2).sum()) / total ** 2 if total > 0 else float("nan")
    mean = float(weights.mean())
    # Population sd (ddof=0) is the one for which DEFF = 1 + CV^2 holds exactly.
    cv = float(weights.std(ddof=0) / mean) if mean > 0 else float("nan")
    minimum, maximum = float(weights.min()), float(weights.max())
    return {
        "n": n,
        "sum_weights": total,
        "minimum": minimum,
        "maximum": maximum,
        "cv": cv,
        "ratio": maximum / minimum if minimum > 0 else float("inf"),
        "deff": deff,
        "effective_n": n / deff if deff and math.isfinite(deff) and deff > 0 else float("nan"),
    }''',
)

SURVEY_DOMAINS = register_helper(
    "survey_domains",
    '''def survey_domains(frame, group_by=None):
    """Domain indicators in sorted label order, so the table is stable."""
    if not group_by:
        return [("(all respondents)", np.ones(len(frame), dtype=bool))]
    labels = frame[group_by].astype(str).agg(" / ".join, axis=1)
    return [(label, (labels == label).to_numpy()) for label in sorted(labels.unique())]''',
)

ESTIMATE_ROW = register_helper(
    "estimate_row",
    '''def estimate_row(label, estimate, value_key):
    """One row of an estimate table, with the estimate at index 1.

    Column order is load-bearing: the product plots the second column, so a
    sample size there would put group sizes under a title promising means.
    """
    unweighted_key = "unweighted_mean" if value_key == "weighted_mean" else "unweighted_sum"
    return {
        "label": label,
        value_key: estimate["value"],
        unweighted_key: estimate["unweighted"],
        "n": estimate["n"],
        "sum_of_weights": estimate["sum_weights"],
        "standard_error": estimate["standard_error"],
        "ci95_low": estimate["ci_low"],
        "ci95_high": estimate["ci_high"],
        "relative_se": estimate["relative_se"],
    }''',
)

RAO_SCOTT = register_helper(
    "rao_scott_factor",
    '''def rao_scott_factor(design, rows, columns, proportions):
    """First-order Rao-Scott correction factor (Rao & Scott 1984).

    Pearson's statistic computed on survey-weighted proportions is not
    chi-square distributed; it is a weighted sum of chi-squares whose weights
    are the generalized design effects. Dividing by their mean,

        delta = [ sum_ij (1 - p_ij) d_ij - sum_i (1 - p_i+) d_i+
                  - sum_j (1 - p_+j) d_+j ] / ((r - 1)(c - 1))

    restores an approximate chi-square reference. Under equal weights every d is
    1 and delta is exactly 1, so nothing is corrected.
    """
    row_labels = sorted(rows.unique())
    column_labels = sorted(columns.unique())
    cell = np.array([
        [
            survey_design_effect(design, ((rows == a) & (columns == b)).to_numpy().astype(float))
            for b in column_labels
        ]
        for a in row_labels
    ])
    row_deff = np.array([
        survey_design_effect(design, (rows == a).to_numpy().astype(float)) for a in row_labels
    ])
    column_deff = np.array([
        survey_design_effect(design, (columns == b).to_numpy().astype(float))
        for b in column_labels
    ])
    row_margin = proportions.sum(axis=1)
    column_margin = proportions.sum(axis=0)
    bracket = (
        float(((1 - proportions) * cell).sum())
        - float(((1 - row_margin) * row_deff).sum())
        - float(((1 - column_margin) * column_deff).sum())
    )
    return bracket / ((len(row_labels) - 1) * (len(column_labels) - 1))''',
    requires=(SURVEY_DEFF,),
)

PEARSON_X2 = register_helper(
    "pearson_x2",
    '''def pearson_x2(proportions, scale):
    """Pearson's X^2 for a table of proportions scaled to *scale* observations."""
    expected = np.outer(proportions.sum(axis=1), proportions.sum(axis=0))
    return float(scale * (((proportions - expected) ** 2) / expected).sum())''',
)


# ---------------------------------------------------------------------------
# Shared emitter pieces
# ---------------------------------------------------------------------------


def _design_lines(params: dict[str, Any], index: int, *, numeric_outcome: bool = True) -> Lines:
    """The listwise-deleted frame and the coded design matrix, as the product built them."""
    also = [params["exposure"]] if params.get("exposure") else []
    extra = f", also_required={py_literal(also)}" if also else ""
    if not numeric_outcome:
        extra += ", numeric_outcome=False"
    return [
        "# The product refuses a design it cannot support — a constant regressor,",
        "# perfect collinearity, an outcome that is an exact function of its own",
        "# regressors — before fitting. This analysis passed those guards.",
        f"frame_{index}, exog_{index}, references_{index} = regression_design(",
        f"    {DATA}, {py_literal(params['y'])}, {py_literal(list(params['x']))}{extra}",
        ")",
        f"if references_{index}:",
        f"    print('Categorical baselines:', references_{index})",
    ]


def _focal_lines(index: int) -> Lines:
    """The regressor a headline interval describes: the first term the spec named."""
    return [
        "# The headline interval describes the first term of the first regressor the",
        "# question named; every other term's interval is in the table.",
        f"focal_{index} = result_{index}.loc[",
        f"    result_{index}['term'] == exog_{index}.columns[1]",
        "].iloc[0]",
    ]


def _sample_lines(index: int) -> Lines:
    return [
        f"    'n': int(len(frame_{index})),",
        f"    'n_excluded': int(len({DATA}) - len(frame_{index})),",
    ]


def _robust(params: dict[str, Any], default: str) -> str | None:
    choice = str(params.get("robust", default))
    return None if choice == "none" else choice


# ---------------------------------------------------------------------------
# Tier 4 — regression
# ---------------------------------------------------------------------------


@register(
    "ols",
    REGRESSION_DESIGN,
    COEFFICIENT_TABLE,
    VIF_TABLE,
    imports=(_SM_NOTE, _SM, _BREUSCH_PAGAN, _VIF, _DURBIN_WATSON, _JARQUE_BERA),
)
def _emit_ols(params: dict[str, Any], label: str, index: int) -> Lines:
    robust = _robust(params, "HC3")
    # use_t keeps the reported statistic a t and the interval a t interval under
    # a robust covariance; statsmodels otherwise switches silently to the normal.
    fit = (
        f"sm.OLS(values_{index}, exog_{index}).fit(cov_type={py_literal(robust)}, use_t=True)"
        if robust
        else f"sm.OLS(values_{index}, exog_{index}).fit()"
    )
    return [
        *_design_lines(params, index),
        f"values_{index} = frame_{index}[{py_literal(params['y'])}].to_numpy(dtype=float)",
        f"fit_{index} = {fit}",
        f"result_{index} = coefficient_table(fit_{index}, 't')",
        f"residuals_{index} = np.asarray(fit_{index}.resid, dtype=float)",
        f"ss_residual_{index} = float(residuals_{index} @ residuals_{index})",
        *_focal_lines(index),
        f"stats_{index} = {{",
        f"    'standard_errors': {py_literal(robust or 'classical')},",
        *_sample_lines(index),
        f"    'df_model': int(fit_{index}.df_model),",
        f"    'df_resid': int(fit_{index}.df_resid),",
        f"    'r_squared': float(fit_{index}.rsquared),",
        f"    'adj_r_squared': float(fit_{index}.rsquared_adj),",
        f"    'f_statistic': float(fit_{index}.fvalue),",
        f"    'f_p_value': floored_p(fit_{index}.f_pvalue),",
        f"    'rmse': math.sqrt(ss_residual_{index} / len(frame_{index})),",
        f"    'residual_std_error': math.sqrt(ss_residual_{index} / float(fit_{index}.df_resid)),",
        f"    'aic': float(fit_{index}.aic),",
        f"    'bic': float(fit_{index}.bic),",
        f"    'ci95_low': float(focal_{index}['ci_low']),",
        f"    'ci95_high': float(focal_{index}['ci_high']),",
        f"    'effect_size': float(fit_{index}.rsquared),",
        "    # The diagnostics the product reports as assumption checks.",
        f"    'breusch_pagan_p': float("
        f"het_breuschpagan(residuals_{index}, fit_{index}.model.exog)[1]),",
        f"    'durbin_watson': float(durbin_watson(residuals_{index})),",
        f"    'jarque_bera_p': float(jarque_bera(residuals_{index})[1]),",
        "}",
        f"print(vif_table(exog_{index}).to_string(index=False))",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@register(
    "logit",
    REGRESSION_DESIGN,
    COEFFICIENT_TABLE,
    SUCCESS_INDICATOR,
    VIF_TABLE,
    imports=(_SM_NOTE, _SM, _VIF),
)
def _emit_logit(params: dict[str, Any], label: str, index: int) -> Lines:
    robust = _robust(params, "none")
    fit = f"sm.Logit(values_{index}, exog_{index}).fit(disp=0" + (
        f", cov_type={py_literal(robust)})" if robust else ")"
    )
    return [
        *_design_lines(params, index, numeric_outcome=False),
        f"values_{index} = success_indicator(",
        f"    frame_{index}[{py_literal(params['y'])}], {py_literal(params['success_value'])}",
        ")",
        f"successes_{index} = int(values_{index}.sum())",
        f"fit_{index} = {fit}",
        "# Odds ratios are exp(coefficient), and their interval is exp of the",
        "# coefficient's interval — not a symmetric interval around the ratio.",
        f"result_{index} = coefficient_table(fit_{index}, 'z', ratio={py_literal(ODDS_RATIO)})",
        *_focal_lines(index),
        f"stats_{index} = {{",
        f"    'standard_errors': {py_literal(robust or 'classical (observed information)')},",
        *_sample_lines(index),
        f"    'successes': successes_{index},",
        f"    'base_rate': successes_{index} / len(frame_{index}),",
        f"    'df_model': int(fit_{index}.df_model),",
        f"    'df_resid': int(fit_{index}.df_resid),",
        f"    'log_likelihood': float(fit_{index}.llf),",
        f"    'null_log_likelihood': float(fit_{index}.llnull),",
        "    # McFadden's: not a share of variance, and small values are normal.",
        f"    'pseudo_r_squared': float(fit_{index}.prsquared),",
        f"    'llr_statistic': float(fit_{index}.llr),",
        f"    'llr_p_value': floored_p(fit_{index}.llr_pvalue),",
        f"    'aic': float(fit_{index}.aic),",
        f"    'bic': float(fit_{index}.bic),",
        f"    'ci95_low': float(focal_{index}[{py_literal(ODDS_RATIO[1])}]),",
        f"    'ci95_high': float(focal_{index}[{py_literal(ODDS_RATIO[2])}]),",
        "    # Chinn's conversion: a log-odds ratio divided by pi/sqrt(3) — the",
        "    # standard deviation of the logistic — is on Cohen's d scale.",
        f"    'effect_size': float(focal_{index}['coefficient']) "
        f"* {py_literal(LOGISTIC_TO_COHEN_D)},",
        "}",
        f"print(vif_table(exog_{index}).to_string(index=False))",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _count_fit(params: dict[str, Any], index: int) -> Lines:
    """The fit and its Pearson dispersion, which differ between the two families."""
    exposure = (
        f"frame_{index}[{py_literal(params['exposure'])}].to_numpy(dtype=float)"
        if params.get("exposure")
        else "None"
    )
    lines = [f"exposure_{index} = {exposure}"]
    if params.get("exposure"):
        lines.append(
            "# log(exposure) enters as a fixed offset, so the coefficients describe rates."
        )
    if str(params.get("family", "poisson")) == "poisson":
        return lines + [
            f"fit_{index} = sm.GLM(",
            f"    values_{index}, exog_{index}, family=sm.families.Poisson(),"
            f" exposure=exposure_{index}",
            ").fit()",
            f"chi_square_{index} = float(fit_{index}.pearson_chi2)",
            f"df_resid_{index} = float(fit_{index}.df_resid)",
            f"result_{index} = coefficient_table(fit_{index}, 'z', ratio={py_literal(RATE_RATIO)})",
        ]
    return lines + [
        f"fit_{index} = sm.NegativeBinomial(",
        f"    values_{index}, exog_{index}, loglike_method='nb2', exposure=exposure_{index}",
        ").fit(disp=0)",
        "# Pearson chi-square under the NB2 variance mu + alpha*mu^2. alpha is the",
        "# overdispersion parameter the model estimates; alpha = 0 is the Poisson.",
        f"alpha_{index} = float(fit_{index}.params['alpha'])",
        f"mu_{index} = np.asarray(fit_{index}.predict(), dtype=float)",
        f"chi_square_{index} = float(np.sum(",
        f"    (values_{index} - mu_{index}) ** 2 / (mu_{index} + alpha_{index} * mu_{index} ** 2)",
        "))",
        f"df_resid_{index} = float(fit_{index}.df_resid)",
        f"result_{index} = coefficient_table(",
        f"    fit_{index}, 'z', exclude=('alpha',), ratio={py_literal(RATE_RATIO)}",
        ")",
    ]


@register(
    "count_model",
    REGRESSION_DESIGN,
    COEFFICIENT_TABLE,
    VIF_TABLE,
    imports=(_SM_NOTE, _SM, _VIF),
)
def _emit_count_model(params: dict[str, Any], label: str, index: int) -> Lines:
    family = str(params.get("family", "poisson"))
    return [
        *_design_lines(params, index),
        f"values_{index} = frame_{index}[{py_literal(params['y'])}].to_numpy(dtype=float)",
        *_count_fit(params, index),
        *_focal_lines(index),
        f"stats_{index} = {{",
        f"    'family': {py_literal(family)},",
        *_sample_lines(index),
        f"    'df_model': int(fit_{index}.df_model),",
        f"    'df_resid': int(df_resid_{index}),",
        f"    'mean_outcome': float(values_{index}.mean()),",
        f"    'variance_outcome': float(values_{index}.var(ddof=1)),",
        f"    'log_likelihood': float(fit_{index}.llf),",
        f"    'null_log_likelihood': float(fit_{index}.llnull),",
        f"    'pseudo_r_squared': 1 - float(fit_{index}.llf) / float(fit_{index}.llnull),",
        f"    'aic': float(fit_{index}.aic),",
        f"    'bic': float(fit_{index}.bic),",
        "    # Pearson chi-square over residual df. Near 1 is what the family assumes;",
        "    # well above 1 means every p-value beside these coefficients is optimistic.",
        f"    'pearson_chi2': chi_square_{index},",
        f"    'dispersion_ratio': chi_square_{index} / df_resid_{index},",
        f"    'dispersion_p_value': float(stats.chi2.sf(chi_square_{index},"
        f" int(df_resid_{index}))),",
        f"    'ci95_low': float(focal_{index}[{py_literal(RATE_RATIO[1])}]),",
        f"    'ci95_high': float(focal_{index}[{py_literal(RATE_RATIO[2])}]),",
        "    # The incidence rate ratio: the multiplicative change in the expected",
        "    # count. It has no conventional magnitude scale; 1.0 is no effect.",
        f"    'effect_size': float(focal_{index}[{py_literal(RATE_RATIO[0])}]),",
        "}",
        f"print(vif_table(exog_{index}).to_string(index=False))",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@register(
    "quantile_regression",
    REGRESSION_DESIGN,
    COEFFICIENT_TABLE,
    VIF_TABLE,
    imports=(_SM_NOTE, _QUANTREG, _VIF),
)
def _emit_quantile_regression(params: dict[str, Any], label: str, index: int) -> Lines:
    tau = float(params.get("tau", DEFAULT_TAU))
    return [
        *_design_lines(params, index),
        f"values_{index} = frame_{index}[{py_literal(params['y'])}].to_numpy(dtype=float)",
        "# Each coefficient is the change in this quantile of the outcome per unit of",
        "# the regressor — a different question from the change in its mean. The",
        "# standard errors are the Huber sandwich, statsmodels' QuantReg default.",
        f"fit_{index} = QuantReg(values_{index}, exog_{index}).fit(",
        f"    q={py_literal(tau)}, max_iter={py_literal(QUANTREG_MAX_ITER)}",
        ")",
        f"result_{index} = coefficient_table(fit_{index}, 't')",
        f"residuals_{index} = np.asarray(fit_{index}.resid, dtype=float)",
        *_focal_lines(index),
        f"stats_{index} = {{",
        f"    'tau': {py_literal(tau)},",
        *_sample_lines(index),
        f"    'df_model': int(fit_{index}.df_model),",
        f"    'df_resid': int(fit_{index}.df_resid),",
        "    # Koenker-Machado: goodness of fit at this quantile only.",
        f"    'pseudo_r_squared': float(fit_{index}.prsquared),",
        f"    'share_below_fit': float(np.mean(residuals_{index} < 0)),",
        f"    'ci95_low': float(focal_{index}['ci_low']),",
        f"    'ci95_high': float(focal_{index}['ci_high']),",
        f"    'effect_size': float(fit_{index}.prsquared),",
        "}",
        f"print(vif_table(exog_{index}).to_string(index=False))",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 5 — time series
# ---------------------------------------------------------------------------


def _grid_lines(params: dict[str, Any], index: int, columns: list[str]) -> Lines:
    freq = params.get("freq")
    agg = str(params.get("agg", "mean"))
    return [
        f"grid_{index}, freq_{index}, interpolated_{index} = series_grid(",
        f"    {DATA}, {py_literal(params['date'])}, {py_literal(columns)},",
        f"    freq={py_literal(freq)}, agg={py_literal(agg)},",
        ")",
        "print('{} periods on a {} grid, {} of them interpolated.'.format(",
        f"    len(grid_{index}), freq_{index}, interpolated_{index}))",
    ]


def _seasonal_period_map() -> str:
    """The frequency-to-cycle table, as a Python dict literal."""
    pairs = ", ".join(
        f"{py_literal(key)}: {py_literal(value)}" for key, value in SEASONAL_PERIODS.items()
    )
    return "{" + pairs + "}"


def _period_lines(params: dict[str, Any], index: int) -> Lines:
    declared = params.get("seasonal_period")
    if declared is not None:
        return [f"period_{index} = {py_literal(int(declared))}"]
    return [
        "# The cycle the frequency implies. Yearly data has none shorter than one",
        "# observation, which is why the product requires it to be stated there.",
        f"period_{index} = {_seasonal_period_map()}[freq_{index}]",
    ]


@register(
    "decompose",
    SERIES_GRID,
    INFER_FREQ,
    COMPONENT_STRENGTH,
    SLOPE_INTERVAL,
    LJUNG_BOX,
    imports=(_SM_NOTE, _LJUNGBOX, _STL, _CLASSICAL),
)
def _emit_decompose(params: dict[str, Any], label: str, index: int) -> Lines:
    column = py_literal(params["value"])
    return [
        *_grid_lines(params, index, [params["value"]]),
        *_period_lines(params, index),
        f"series_{index} = grid_{index}[{column}]",
        "# STL estimates a seasonal component that evolves, which needs more history",
        "# than the classical fixed-seasonal average; below three cycles it is the",
        "# classical method or nothing.",
        f"if len(series_{index}) >= {py_literal(STL_MIN_CYCLES)} * period_{index}:",
        "    # A locally-constant seasonal smoother spanning two cycles. STL's default",
        "    # of 7 fits noise into the seasonal component: on white noise the usual",
        "    # seasonal-strength measure comes out near 0.4 rather than near 0.",
        f"    window_{index} = {py_literal(STL_SEASONAL_CYCLES)} * period_{index} + 1",
        f"    window_{index} = max(7, window_{index} if window_{index} % 2"
        f" else window_{index} + 1)",
        f"    fitted_{index} = STL(",
        f"        series_{index}, period=period_{index}, seasonal=window_{index}, seasonal_deg=0",
        "    ).fit()",
        f"    method_{index} = 'STL (LOESS, seasonal window {{}})'.format(window_{index})",
        "else:",
        f"    fitted_{index} = seasonal_decompose("
        f"series_{index}, model='additive', period=period_{index})",
        f"    method_{index} = (",
        "        'classical additive decomposition (a centred moving average; the '",
        "        'series carries {:.1f} cycles, too few for STL)'.format(",
        f"            len(series_{index}) / period_{index}",
        "        )",
        "    )",
        f"trend_{index} = fitted_{index}.trend.to_numpy()",
        f"seasonal_{index} = fitted_{index}.seasonal.to_numpy()",
        f"residual_{index} = fitted_{index}.resid.to_numpy()",
        "",
        f"result_{index} = pd.DataFrame({{",
        f"    'date': grid_{index}.index,",
        f"    'observed': series_{index}.to_numpy(),",
        f"    'trend': trend_{index},",
        f"    'seasonal': seasonal_{index},",
        f"    'residual': residual_{index},",
        "})",
        f"slope_{index}, slope_low_{index}, slope_high_{index} ="
        f" slope_with_interval(trend_{index})",
        f"peak_to_trough_{index} = float(np.nanmax(seasonal_{index})"
        f" - np.nanmin(seasonal_{index}))",
        f"lb_{index}, lb_p_{index}, lb_dof_{index} = ljung_box(",
        f"    residual_{index}, min(2 * period_{index}, {py_literal(MAX_LAGS)})",
        ")",
        f"stats_{index} = {{",
        f"    'method': method_{index},",
        f"    'seasonal_period': int(period_{index}),",
        f"    'periods': int(len(grid_{index})),",
        f"    'periods_interpolated': int(interpolated_{index}),",
        "    # Strength on [0, 1]: 1 - Var(remainder) / Var(remainder + component).",
        "    # It describes this decomposition; it is not a test.",
        f"    'trend_strength': component_strength(residual_{index}, trend_{index}),",
        f"    'seasonal_strength': component_strength(residual_{index}, seasonal_{index}),",
        f"    'trend_slope_per_period': slope_{index},",
        f"    'seasonal_amplitude': peak_to_trough_{index} / 2,",
        f"    'seasonal_peak_to_trough': peak_to_trough_{index},",
        f"    'residual_sd': float(np.nanstd(residual_{index}, ddof=1)),",
        f"    'ci95_low': slope_low_{index},",
        f"    'ci95_high': slope_high_{index},",
        f"    'effect_size': component_strength(residual_{index}, seasonal_{index}),",
        f"    'ljung_box_p': lb_p_{index},",
        "}",
        f"show({py_literal(label)}, result_{index}.head(), stats_{index})",
    ]


@register(
    "stationarity_test",
    SERIES_GRID,
    INFER_FREQ,
    imports=(_SM_NOTE, _RESULT_OBJECT_NOTE, _ACF, _ADFULLER, _KPSS),
)
def _emit_stationarity_test(params: dict[str, Any], label: str, index: int) -> Lines:
    column = py_literal(params["value"])
    regression = py_literal(str(params.get("regression", "c")))
    floor = py_literal(MACKINNON_P_FLOOR)
    return [
        *_grid_lines(params, index, [params["value"]]),
        f"values_{index} = grid_{index}[{column}].to_numpy(dtype=float)",
        "# Two tests with OPPOSITE nulls. ADF's null is a unit root; KPSS's null is",
        "# stationarity. Their disagreement is the informative part: it separates a",
        "# unit root (difference it) from a deterministic trend (detrend it).",
        f"adf_{index} = adfuller(",
        f"    values_{index}, regression={regression}, autolag='AIC', result_object=True",
        ")",
        "# MacKinnon's p-value is a polynomial approximation that underflows to 0 for",
        "# a strongly mean-reverting series; 0 is a claim no test can support.",
        f"adf_p_{index} = max(float(adf_{index}.pvalue), {floor})",
        "# statsmodels warns when the KPSS statistic falls outside its published",
        "# table. That warning means the p-value is a bound, not a measurement.",
        f"kpss_{index} = kpss(",
        f"    values_{index}, regression={regression}, nlags='auto', result_object=True",
        ")",
        f"kpss_p_{index} = float(kpss_{index}.pvalue)",
        "",
        f"result_{index} = pd.DataFrame([",
        "    {",
        "        'test': 'Augmented Dickey-Fuller',",
        f"        'statistic': float(adf_{index}.statistic),",
        f"        'p_value': adf_p_{index},",
        f"        'lags_used': int(adf_{index}.lags),",
        f"        'critical_1pct': float(adf_{index}.critical_values['1%']),",
        f"        'critical_5pct': float(adf_{index}.critical_values['5%']),",
        f"        'critical_10pct': float(adf_{index}.critical_values['10%']),",
        f"        'null_hypothesis_rejected': bool(adf_p_{index} < {py_literal(ALPHA)}),",
        "    },",
        "    {",
        "        'test': 'KPSS',",
        f"        'statistic': float(kpss_{index}.statistic),",
        f"        'p_value': kpss_p_{index},",
        f"        'lags_used': int(kpss_{index}.lags),",
        f"        'critical_1pct': float(kpss_{index}.critical_values['1%']),",
        f"        'critical_5pct': float(kpss_{index}.critical_values['5%']),",
        f"        'critical_10pct': float(kpss_{index}.critical_values['10%']),",
        f"        'null_hypothesis_rejected': bool(kpss_p_{index} < {py_literal(ALPHA)}),",
        "    },",
        "])",
        "# How many differences it takes before ADF rejects a unit root.",
        f"working_{index} = values_{index}",
        f"differences_{index} = {py_literal(MAX_DIFFERENCES + 1)}",
        f"for order_{index} in range({py_literal(MAX_DIFFERENCES + 1)}):",
        f"    if working_{index}.size < {py_literal(MIN_RESIDUAL_PERIODS)}:",
        f"        differences_{index} = order_{index}",
        "        break",
        f"    step_{index} = adfuller(",
        f"        working_{index}, regression={regression}, autolag='AIC', result_object=True",
        "    )",
        f"    if float(step_{index}.pvalue) < {py_literal(ALPHA)}:",
        f"        differences_{index} = order_{index}",
        "        break",
        f"    working_{index} = np.diff(working_{index})",
        "",
        "# Lag-1 autocorrelation with a Bartlett interval — how persistent the series is.",
        f"rho_{index} = float(acf(values_{index}, nlags=1, result_object=True).acf[1])",
        f"margin_{index} = float(stats.norm.ppf("
        f"{py_literal(round((1 + CONFIDENCE_LEVEL) / 2, 10))}"
        f")) / math.sqrt(values_{index}.size)",
        f"stats_{index} = {{",
        f"    'periods': int(len(grid_{index})),",
        f"    'adf_statistic': float(adf_{index}.statistic),",
        f"    'adf_p_value': adf_p_{index},",
        f"    'kpss_statistic': float(kpss_{index}.statistic),",
        f"    'kpss_p_value': kpss_p_{index},",
        f"    'differences_suggested': min(differences_{index},"
        f" {py_literal(MAX_DIFFERENCES + 1)}),",
        f"    'effect_size': rho_{index},",
        f"    'ci95_low': rho_{index} - margin_{index},",
        f"    'ci95_high': rho_{index} + margin_{index},",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@register(
    "autocorrelation",
    SERIES_GRID,
    INFER_FREQ,
    LJUNG_BOX,
    imports=(_SM_NOTE, _RESULT_OBJECT_NOTE, _ACF, _LJUNGBOX, _PACF),
)
def _emit_autocorrelation(params: dict[str, Any], label: str, index: int) -> Lines:
    column = py_literal(params["value"])
    requested = params.get("lags")
    # Box-Jenkins' rule of thumb when the spec does not ask for a lag count.
    wanted = (
        py_literal(int(requested))
        if requested is not None
        else f"max(1, int(round(10 * math.log10(max(values_{index}.size, 10)))))"
    )
    return [
        *_grid_lines(params, index, [params["value"]]),
        f"values_{index} = grid_{index}[{column}].to_numpy(dtype=float)",
        "# Autocorrelations past a quarter of the series rest on too few overlapping",
        "# pairs to mean anything, so the lag count is capped there.",
        f"ceiling_{index} = max(1, min(int(values_{index}.size *"
        f" {py_literal(MAX_LAG_FRACTION)}), {py_literal(MAX_LAGS)}))",
        f"lags_{index} = min({wanted}, ceiling_{index})",
        f"acf_{index} = acf(",
        f"    values_{index}, nlags=lags_{index}, alpha={py_literal(round(1 - CONFIDENCE_LEVEL, 10))},",
        "    bartlett_confint=True, result_object=True,",
        ")",
        f"pacf_{index} = pacf(",
        f"    values_{index}, nlags=lags_{index},"
        f" alpha={py_literal(round(1 - CONFIDENCE_LEVEL, 10))}, result_object=True",
        ")",
        "# Bartlett bands widen with the lag because each estimate is conditional on",
        "# the ones before it; the flat +/- 1.96/sqrt(n) band is too narrow past lag 1.",
        f"result_{index} = pd.DataFrame([",
        "    {",
        "        'lag': lag,",
        f"        'acf': float(acf_{index}.acf[lag]),",
        f"        'acf_ci95_low': float(acf_{index}.confint[lag][0]),",
        f"        'acf_ci95_high': float(acf_{index}.confint[lag][1]),",
        f"        'acf_outside_band': bool(acf_{index}.confint[lag][0] > 0"
        f" or acf_{index}.confint[lag][1] < 0),",
        f"        'pacf': float(pacf_{index}.pacf[lag]),",
        f"        'pacf_ci95_low': float(pacf_{index}.confint[lag][0]),",
        f"        'pacf_ci95_high': float(pacf_{index}.confint[lag][1]),",
        f"        'pacf_outside_band': bool(pacf_{index}.confint[lag][0] > 0"
        f" or pacf_{index}.confint[lag][1] < 0),",
        "    }",
        f"    for lag in range(1, lags_{index} + 1)",
        "])",
        f"lb_{index}, lb_p_{index}, lb_dof_{index} = ljung_box(values_{index}, lags_{index})",
        f"stats_{index} = {{",
        f"    'periods': int(len(grid_{index})),",
        f"    'lags': int(lags_{index}),",
        f"    'ljung_box_statistic': lb_{index},",
        f"    'ljung_box_dof': int(lb_dof_{index}),",
        f"    'ljung_box_p_value': max(lb_p_{index}, {py_literal(LJUNG_BOX_P_FLOOR)}),",
        f"    'effect_size': float(acf_{index}.acf[1]),",
        f"    'ci95_low': float(acf_{index}.confint[1][0]),",
        f"    'ci95_high': float(acf_{index}.confint[1][1]),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


def _arima_orders(params: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int, int]]:
    order = (int(params["p"]), int(params["d"]), int(params["q"]))
    seasonal = {key: int(params[key]) for key in ("P", "D", "Q") if key in params}
    if not seasonal:
        return order, (0, 0, 0, 0)
    return order, (
        seasonal.get("P", 0),
        seasonal.get("D", 0),
        seasonal.get("Q", 0),
        int(params["seasonal_period"]),
    )


def _forecast_lines(params: dict[str, Any], index: int) -> Lines:
    """Observed history then forecast rows, each marked and each carrying its interval."""
    steps = int(params["forecast_periods"])
    return [
        "# A forecast is a claim about the future stated in the same typeface as a",
        "# measurement, so every forecast row is marked and carries its prediction",
        "# interval. That interval assumes THIS model is the right one; it does not",
        "# cover the risk that it is not, and it widens with each step ahead.",
        f"summary_{index} = fitted_{index}.get_forecast(steps={py_literal(steps)})"
        f".summary_frame(alpha={py_literal(round(1 - CONFIDENCE_LEVEL, 10))})",
        f"context_{index} = min(",
        f"    {py_literal(FORECAST_CONTEXT_MULTIPLE)} * {py_literal(steps)},"
        f" {py_literal(MAX_FORECAST_CONTEXT)}, observed_{index}.size",
        ")",
        f"tail_{index} = observed_{index}.iloc[-context_{index}:]",
        f"result_{index} = pd.concat([",
        "    pd.DataFrame({",
        f"        'date': tail_{index}.index,",
        f"        'value': tail_{index}.to_numpy(dtype=float),",
        "        'ci95_low': np.nan,",
        "        'ci95_high': np.nan,",
        "        'kind': 'observed',",
        "    }),",
        "    pd.DataFrame({",
        f"        'date': summary_{index}.index,",
        f"        'value': summary_{index}['mean'].to_numpy(dtype=float),",
        f"        'ci95_low': summary_{index}['mean_ci_lower'].to_numpy(dtype=float),",
        f"        'ci95_high': summary_{index}['mean_ci_upper'].to_numpy(dtype=float),",
        "        'kind': 'forecast',",
        "    }),",
        "], ignore_index=True)",
    ]


@register(
    "arima",
    SERIES_GRID,
    INFER_FREQ,
    COMPONENT_STRENGTH,
    LJUNG_BOX,
    ARIMA_TABLE,
    imports=(_SM_NOTE, _ARIMA, _LJUNGBOX),
)
def _emit_arima(params: dict[str, Any], label: str, index: int) -> Lines:
    column = py_literal(params["value"])
    order, seasonal = _arima_orders(params)
    model_df = order[0] + order[2] + (seasonal[0] + seasonal[2]) * (seasonal[3] or 1)
    lines = [
        *_grid_lines(params, index, [params["value"]]),
        f"observed_{index} = grid_{index}[{column}]",
        f"fitted_{index} = ARIMA(",
        f"    observed_{index}, order={py_literal(order)}, seasonal_order={py_literal(seasonal)}",
        ").fit()",
        f"coefficients_{index} = arima_coefficient_table(fitted_{index})",
        f"residual_{index} = np.asarray(fitted_{index}.resid, dtype=float)",
        f"lb_{index}, lb_p_{index}, lb_dof_{index} = ljung_box(",
        f"    residual_{index}, min(2 * ({py_literal(model_df)} + 1) + 8,"
        f" {py_literal(MAX_LAGS)}), model_df={py_literal(model_df)}",
        ")",
    ]
    if params.get("forecast_periods") is None:
        lines.append(f"result_{index} = coefficients_{index}")
    else:
        lines += _forecast_lines(params, index)
    headline = "ar.L1" if order[0] else ("ma.L1" if order[2] else "const")
    return lines + [
        f"headline_{index} = coefficients_{index}.loc[",
        f"    coefficients_{index}['term'] == {py_literal(headline)}",
        "]",
        f"headline_{index} = (",
        f"    headline_{index}.iloc[0] if len(headline_{index}) else coefficients_{index}.iloc[0]",
        ")",
        f"stats_{index} = {{",
        f"    'periods': int(len(grid_{index})),",
        f"    'aic': float(fitted_{index}.aic),",
        f"    'bic': float(fitted_{index}.bic),",
        f"    'hqic': float(fitted_{index}.hqic),",
        f"    'log_likelihood': float(fitted_{index}.llf),",
        f"    'sigma2': float(fitted_{index}.mse),",
        f"    'ljung_box_p': lb_p_{index},",
        f"    'ci95_low': float(headline_{index}['ci95_low']),",
        f"    'ci95_high': float(headline_{index}['ci95_high']),",
        "    # In-sample fit, not out-of-sample accuracy.",
        "    'effect_size': component_strength(",
        f"        residual_{index}, observed_{index}.to_numpy(dtype=float) - residual_{index}",
        "    ),",
        "}",
        f"print(coefficients_{index}.to_string(index=False))",
        f"show({py_literal(label)}, result_{index}.head(), stats_{index})",
    ]


@register(
    "granger_causality",
    SERIES_GRID,
    INFER_FREQ,
    BH_ADJUST,
    imports=(_SM_NOTE, _RESULT_OBJECT_NOTE, _ADFULLER, _GRANGER, _OLS),
)
def _emit_granger_causality(params: dict[str, Any], label: str, index: int) -> Lines:
    outcome, cause = params["value"], params["cause"]
    requested = params.get("max_lag")
    wanted = py_literal(int(requested)) if requested is not None else "4"
    floor = py_literal(MACKINNON_P_FLOOR)
    return [
        "# Granger causality is predictive PRECEDENCE, not causation: it says past",
        "# values of the cause improve the forecast of the outcome, which is equally",
        "# consistent with a common driver, a reporting lag, or coincidence.",
        *_grid_lines(params, index, [outcome, cause]),
        "# Both series are differenced together — the same number of times whether or",
        "# not both needed it — because comparing lags of a level against lags of a",
        "# difference compares different quantities. A Granger test on non-stationary",
        "# series manufactures significance.",
        f"working_{index} = grid_{index}[{py_literal([outcome, cause])}]",
        f"differences_{index} = 0",
        f"for differences_{index} in range({py_literal(MAX_DIFFERENCES + 1)}):",
        f"    adf_{index} = {{",
        "        name: adfuller(",
        f"            working_{index}[name].to_numpy(dtype=float), regression='c', autolag='AIC',",
        "            result_object=True,",
        "        )",
        f"        for name in {py_literal([outcome, cause])}",
        "    }",
        f"    if all(max(float(entry.pvalue), {floor}) < {py_literal(ALPHA)}"
        f" for entry in adf_{index}.values()):",
        "        break",
        f"    working_{index} = working_{index}.diff().dropna()",
        "",
        f"outcome_{index} = working_{index}[{py_literal(outcome)}].to_numpy(dtype=float)",
        f"cause_{index} = working_{index}[{py_literal(cause)}].to_numpy(dtype=float)",
        "# Lags are bounded so the unrestricted model keeps degrees of freedom.",
        f"ceiling_{index} = max(1, min(int(len(working_{index}) *"
        f" {py_literal(MAX_LAG_FRACTION)}) // 2, {py_literal(MAX_LAGS)}))",
        f"max_lag_{index} = min({wanted}, ceiling_{index})",
        f"tests_{index} = grangercausalitytests(",
        f"    np.column_stack([outcome_{index}, cause_{index}]), maxlag=max_lag_{index}",
        ")",
        f"rows_{index} = []",
        f"for lag_{index} in sorted(tests_{index}, key=int):",
        f"    f_statistic, raw_p, df_denom, df_num = tests_{index}[lag_{index}][0]['ssr_ftest']",
        "    # Partial eta squared: the share of the outcome's otherwise-unexplained",
        "    # variance that the lagged cause accounts for.",
        "    eta = float(f_statistic) * float(df_num) / (float(f_statistic) * float(df_num)"
        " + float(df_denom))",
        f"    rows_{index}.append({{",
        f"        'lag': int(lag_{index}),",
        "        'f_statistic': float(f_statistic),",
        "        'df_num': float(df_num),",
        "        'df_denom': float(df_denom),",
        f"        'p_value': max(float(raw_p), {py_literal(COEFFICIENT_P_FLOOR)}),",
        "        'partial_eta_squared': eta,",
        "    })",
        f"adjusted_{index} = bh_adjust([row['p_value'] for row in rows_{index}])",
        f"for row, value in zip(rows_{index}, adjusted_{index}):",
        "    row['p_value_adjusted'] = value",
        f"    row['significant_at_0.05'] = bool(value < {py_literal(ALPHA)})",
        f"result_{index} = pd.DataFrame(rows_{index})",
        "",
        f"best_{index} = min(rows_{index}, key=lambda row: row['p_value_adjusted'])",
        "# The F-test says whether the lagged cause matters; the summed coefficient",
        "# says by how much and in which direction, which an F cannot.",
        f"lag_{index} = best_{index}['lag']",
        f"rows_used_{index} = outcome_{index}.size - lag_{index}",
        f"design_{index} = np.column_stack(",
        f"    [np.ones(rows_used_{index})]",
        f"    + [outcome_{index}[lag_{index} - s:outcome_{index}.size - s]"
        f" for s in range(1, lag_{index} + 1)]",
        f"    + [cause_{index}[lag_{index} - s:cause_{index}.size - s]"
        f" for s in range(1, lag_{index} + 1)]",
        ")",
        f"summed_{index} = OLS(outcome_{index}[lag_{index}:], design_{index}).fit()",
        f"contrast_{index} = np.zeros(design_{index}.shape[1])",
        f"contrast_{index}[1 + lag_{index}:] = 1.0",
        f"total_{index} = float(contrast_{index} @ summed_{index}.params)",
        f"variance_{index} = float("
        f"contrast_{index} @ summed_{index}.cov_params() @ contrast_{index})",
        f"margin_{index} = float(stats.t.ppf(",
        f"    {py_literal(round((1 + CONFIDENCE_LEVEL) / 2, 10))}, summed_{index}.df_resid",
        f")) * math.sqrt(variance_{index})",
        f"stats_{index} = {{",
        f"    'periods': int(len(working_{index})),",
        f"    'max_lag': int(max_lag_{index}),",
        f"    'differences_applied': int(differences_{index}),",
        f"    'best_lag': int(best_{index}['lag']),",
        f"    'effect_size': best_{index}['partial_eta_squared'],",
        f"    'ci95_low': total_{index} - margin_{index},",
        f"    'ci95_high': total_{index} + margin_{index},",
        "    # Read p_value_adjusted, not p_value: several lags were tested.",
        f"    'adjustment': 'Benjamini-Hochberg across the {{}} lag(s) tested'"
        f".format(len(rows_{index})),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 6 — survey estimation
# ---------------------------------------------------------------------------


def _survey_lines(
    params: dict[str, Any],
    index: int,
    *,
    numeric: list[str],
    labels: list[str],
) -> Lines:
    return [
        f"frame_{index}, design_{index} = survey_data(",
        f"    {DATA}, {py_literal(params['weights'])},",
        f"    numeric_columns={py_literal(numeric)}, label_columns={py_literal(labels)},",
        f"    strata={py_literal(params.get('strata'))},"
        f" cluster={py_literal(params.get('cluster'))},",
        f"    fpc={py_literal(params.get('fpc'))},",
        ")",
    ]


def _group_column(params: dict[str, Any]) -> str:
    group_by = params.get("group_by")
    return " / ".join(group_by) if group_by else "measure"


def _grouped_estimate(params: dict[str, Any], label: str, index: int, *, of_total: bool) -> Lines:
    column = params["column"]
    group_by = list(params.get("group_by") or [])
    value_key = "weighted_total" if of_total else "weighted_mean"
    return [
        *_survey_lines(params, index, numeric=[column], labels=group_by),
        f"values_{index} = frame_{index}[{py_literal(column)}].to_numpy(dtype=float)",
        f"estimates_{index} = {{",
        f"    name: survey_estimate(design_{index}, values_{index}, indicator,"
        f" of_total={py_literal(of_total)})",
        f"    for name, indicator in survey_domains(frame_{index}, {py_literal(group_by)})",
        "}",
        f"result_{index} = pd.DataFrame([",
        f"    estimate_row(name, estimate, {py_literal(value_key)})",
        f"    for name, estimate in estimates_{index}.items()",
        f"]).rename(columns={{'label': {py_literal(_group_column(params))}}})",
        f"stats_{index} = {{",
        f"    'n': int(len(frame_{index})),",
        f"    'estimated_population': float(design_{index}['weights'].sum()),",
        f"    'degrees_of_freedom': survey_dof(design_{index}),",
        "    # How far weighting moved the answer, in standard deviations: the",
        "    # question a reader has the moment they see two means side by side.",
        "    'effect_size': float(",
        f"        (float((design_{index}['weights'] * values_{index}).sum()"
        f" / design_{index}['weights'].sum())",
        f"         - float(values_{index}.mean())) / float(values_{index}.std(ddof=1))",
        "    ),",
        "}",
        f"if len(estimates_{index}) == 1:",
        f"    only_{index} = estimates_{index}['(all respondents)']",
        f"    stats_{index}.update({{",
        f"        {py_literal(value_key)}: only_{index}['value'],",
        f"        'standard_error': only_{index}['standard_error'],",
        f"        'ci95_low': only_{index}['ci_low'],",
        f"        'ci95_high': only_{index}['ci_high'],",
        f"        'relative_standard_error': only_{index}['relative_se'],",
        f"        'sum_of_weights': only_{index}['sum_weights'],",
        "    })",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@register(
    "weighted_mean",
    SURVEY_DATA,
    SURVEY_ESTIMATE,
    SURVEY_DOMAINS,
    ESTIMATE_ROW,
)
def _emit_weighted_mean(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        "# An unweighted mean of a weighted survey is not an approximation of this",
        "# number; it is a different quantity — the people who answered rather than",
        "# the population they were sampled to represent. Both are reported.",
        *_grouped_estimate(params, label, index, of_total=False),
    ]


@register(
    "weighted_total",
    SURVEY_DATA,
    SURVEY_ESTIMATE,
    SURVEY_DOMAINS,
    ESTIMATE_ROW,
)
def _emit_weighted_total(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        "# This total is only as good as the weights' calibration: the weights sum to",
        "# the population size being claimed. If the weight column was not calibrated",
        "# to a real population count, only the relative pattern means anything.",
        *_grouped_estimate(params, label, index, of_total=True),
    ]


@register(
    "design_effect",
    SURVEY_DATA,
    SURVEY_ESTIMATE,
    SURVEY_DEFF,
    WEIGHT_PROFILE,
    SURVEY_DOMAINS,
)
def _emit_design_effect(params: dict[str, Any], label: str, index: int) -> Lines:
    column = params["column"]
    group_by = list(params.get("group_by") or [])
    return [
        "# Kish's design effect comes from the weights alone; the design-based one is",
        "# this variable's actual design variance over what simple random sampling of",
        "# the same n would have given, so it also carries any clustering. They agree",
        "# when the weights are unrelated to the outcome and diverge when they are not.",
        *_survey_lines(params, index, numeric=[column], labels=group_by),
        f"values_{index} = frame_{index}[{py_literal(column)}].to_numpy(dtype=float)",
        f"rows_{index} = []",
        f"for name_{index}, indicator_{index} in survey_domains("
        f"frame_{index}, {py_literal(group_by)}):",
        f"    profile = weight_profile(design_{index}['weights'][indicator_{index}])",
        f"    estimate = survey_estimate(design_{index}, values_{index}, indicator_{index})",
        f"    rows_{index}.append({{",
        f"        'label': name_{index},",
        "        'effective_sample_size': profile['effective_n'],",
        "        'n': profile['n'],",
        "        'design_effect_kish': profile['deff'],",
        "        'design_effect_design_based': survey_design_effect(",
        f"            design_{index}, values_{index}, indicator_{index}",
        "        ),",
        "        'weight_cv': profile['cv'],",
        "        'weight_min': profile['minimum'],",
        "        'weight_max': profile['maximum'],",
        "        'sum_of_weights': profile['sum_weights'],",
        "        'weighted_mean': estimate['value'],",
        "        'unweighted_mean': estimate['unweighted'],",
        "    })",
        f"result_{index} = pd.DataFrame(rows_{index}).rename(",
        f"    columns={{'label': {py_literal(_group_column(params))}}}",
        ")",
        f"overall_{index} = weight_profile(design_{index}['weights'])",
        f"based_{index} = survey_design_effect(design_{index}, values_{index})",
        f"stats_{index} = {{",
        f"    'n': overall_{index}['n'],",
        f"    'design_effect_kish': overall_{index}['deff'],",
        f"    'design_effect_design_based': based_{index},",
        f"    'effective_sample_size': overall_{index}['effective_n'],",
        "    'effective_sample_size_design_based': (",
        f"        overall_{index}['n'] / based_{index}"
        f" if math.isfinite(based_{index}) and based_{index} > 0 else float('nan')",
        "    ),",
        f"    'weight_cv': overall_{index}['cv'],",
        f"    'weight_min': overall_{index}['minimum'],",
        f"    'weight_max': overall_{index}['maximum'],",
        f"    'sum_of_weights': overall_{index}['sum_weights'],",
        f"    'weighted_mean': survey_estimate(design_{index}, values_{index})['value'],",
        f"    'unweighted_mean': float(values_{index}.mean()),",
        f"    'degrees_of_freedom': survey_dof(design_{index}),",
        "    'effect_size': float(",
        f"        (survey_estimate(design_{index}, values_{index})['value']",
        f"         - float(values_{index}.mean())) / float(values_{index}.std(ddof=1))",
        "    ),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@register(
    "weighted_crosstab",
    SURVEY_DATA,
    SURVEY_ESTIMATE,
    SURVEY_DEFF,
    RAO_SCOTT,
    PEARSON_X2,
)
def _emit_weighted_crosstab(params: dict[str, Any], label: str, index: int) -> Lines:
    row, column, weights = params["row"], params["column"], params["weights"]
    return [
        "# The ordinary chi-square on weighted counts treats the sum of the weights as",
        "# if it were a count of independent observations, which is the commonest",
        "# error in published survey analysis. Both statistics are computed below so",
        "# the size of that error is visible.",
        *_survey_lines(params, index, numeric=[], labels=[row, column]),
        f"rows_{index} = frame_{index}[{py_literal(row)}].astype(str)",
        f"columns_{index} = frame_{index}[{py_literal(column)}].astype(str)",
        f"table_{index} = pd.crosstab(",
        f"    rows_{index}, columns_{index},"
        f" values=frame_{index}[{py_literal(weights)}], aggfunc='sum'",
        ").fillna(0.0)",
        f"table_{index} = table_{index}.loc[",
        f"    table_{index}.sum(axis=1) > 0, table_{index}.sum(axis=0) > 0",
        "]",
        f"n_{index} = int(len(frame_{index}))",
        f"population_{index} = float(table_{index}.to_numpy().sum())",
        f"proportions_{index} = table_{index}.to_numpy(dtype=float) / population_{index}",
        "",
        "# Pearson's X^2 at the REAL sample size, then the Rao-Scott correction.",
        f"uncorrected_{index} = pearson_x2(proportions_{index}, n_{index})",
        f"naive_{index} = pearson_x2(proportions_{index}, population_{index})",
        f"factor_{index} = rao_scott_factor(",
        f"    design_{index}, rows_{index}, columns_{index}, proportions_{index}",
        ")",
        f"dof_{index} = (table_{index}.shape[0] - 1) * (table_{index}.shape[1] - 1)",
        f"corrected_{index} = uncorrected_{index} / factor_{index}",
        f"result_{index} = table_{index}.reset_index()",
        f"result_{index}.columns = [str(c) for c in result_{index}.columns]",
        f"stats_{index} = {{",
        "    'correction_type': 'first-order Rao-Scott (mean generalized design effect)',",
        f"    'statistic': corrected_{index},",
        f"    'dof': int(dof_{index}),",
        f"    'p_value': float(stats.chi2.sf(corrected_{index}, dof_{index})),",
        f"    'correction_factor': factor_{index},",
        f"    'uncorrected_statistic': uncorrected_{index},",
        f"    'naive_weighted_statistic': naive_{index},",
        f"    'naive_weighted_p_value': float(stats.chi2.sf(naive_{index}, dof_{index})),",
        f"    'effective_sample_size': n_{index} / factor_{index},",
        f"    'n_unweighted': n_{index},",
        f"    'estimated_population': population_{index},",
        f"    'degrees_of_freedom': survey_dof(design_{index}),",
        "    # Cramer's V from the uncorrected statistic at the real sample size.",
        "    'effect_size': math.sqrt(",
        f"        uncorrected_{index}",
        f"        / (n_{index} * min(table_{index}.shape[0] - 1, table_{index}.shape[1] - 1))",
        "    ),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]


@register(
    "subpopulation_estimate",
    SURVEY_DATA,
    SURVEY_ESTIMATE,
    ESTIMATE_ROW,
)
def _emit_subpopulation_estimate(params: dict[str, Any], label: str, index: int) -> Lines:
    column = params["column"]
    subpopulation = params["subpopulation"]
    wanted = str(params["subpopulation_value"])
    return [
        "# The two rows share a point estimate and differ in the standard error.",
        "# Domain estimation keeps every respondent in the variance calculation and",
        "# uses a 0/1 indicator, so the strata, the PSUs and the degrees of freedom",
        "# stay those of the full design. Filtering first recomputes the variance from",
        "# a smaller design — the domain's sample size is random, not fixed, and",
        "# treating it as fixed is what makes the naive standard error wrong.",
        *_survey_lines(params, index, numeric=[column], labels=[subpopulation]),
        f"values_{index} = frame_{index}[{py_literal(column)}].to_numpy(dtype=float)",
        f"mask_{index} = (",
        f"    frame_{index}[{py_literal(subpopulation)}].astype(str) == {py_literal(wanted)}",
        ").to_numpy()",
        f"domain_{index} = survey_estimate(design_{index}, values_{index}, mask_{index})",
        f"naive_design_{index} = {{",
        f"    'weights': design_{index}['weights'][mask_{index}],",
        f"    'strata': None if design_{index}['strata'] is None"
        f" else design_{index}['strata'][mask_{index}],",
        f"    'clusters': None if design_{index}['clusters'] is None"
        f" else design_{index}['clusters'][mask_{index}],",
        f"    'fpc': design_{index}['fpc'],",
        "}",
        f"naive_{index} = survey_estimate(naive_design_{index}, values_{index}[mask_{index}])",
        f"result_{index} = pd.DataFrame([",
        f"    estimate_row('domain estimation (correct)', domain_{index}, 'weighted_mean'),",
        f"    estimate_row('filter then analyze (naive)', naive_{index}, 'weighted_mean'),",
        "]).rename(columns={'label': 'approach'})",
        f"stats_{index} = {{",
        f"    'n': int(mask_{index}.sum()),",
        f"    'n_out_of_domain': int(len(frame_{index}) - mask_{index}.sum()),",
        f"    'weighted_mean': domain_{index}['value'],",
        f"    'unweighted_mean': domain_{index}['unweighted'],",
        f"    'sum_of_weights': domain_{index}['sum_weights'],",
        f"    'standard_error': domain_{index}['standard_error'],",
        f"    'ci95_low': domain_{index}['ci_low'],",
        f"    'ci95_high': domain_{index}['ci_high'],",
        f"    'degrees_of_freedom': domain_{index}['dof'],",
        f"    'naive_standard_error': naive_{index}['standard_error'],",
        f"    'naive_degrees_of_freedom': naive_{index}['dof'],",
        f"    'standard_error_ratio': naive_{index}['standard_error']"
        f" / domain_{index}['standard_error'],",
        "    'effect_size': float(",
        f"        (domain_{index}['value'] - float(values_{index}[mask_{index}].mean()))",
        f"        / float(values_{index}[mask_{index}].std(ddof=1))",
        "    ),",
        "}",
        f"show({py_literal(label)}, result_{index}, stats_{index})",
    ]
