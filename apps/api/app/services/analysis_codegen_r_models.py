"""R source for the modelled tiers: regression, time series, survey estimation.

:mod:`app.services.analysis_codegen_r` emits Tiers 1 to 3 in dplyr and base
``stats``. The tiers here need the packages a researcher would actually reach
for — ``sandwich``/``lmtest`` for robust standard errors, ``MASS`` for a negative
binomial, ``quantreg`` for a quantile fit, ``tseries``/``urca`` for unit roots,
and above all **``survey``** for Tier 6, because a survey methodologist checking
a weighted estimate will check it with ``svydesign`` and ``svymean`` or not at
all. That last one is the point of this module: it turns a weighted mean the
product printed into something checkable in the tool the reader already uses.

Two rules carry over from the dialect module, and one is added.

**Nothing but a literal.** Column names never appear as R identifiers. That is
harder here than in Tier 1: ``lm`` and ``svymean`` are driven by formulas, and a
formula needs syntactic names. So every block first builds a small frame with
fixed generated names — ``y_``, ``t1_``, ``w_``, ``psu_`` — from columns reached
as ``frame[["..."]]``, fits over that, and maps the product's own term names back
onto the coefficient table afterwards. No backticks, no ``make.names``, and the
printed table still says ``region[North]``.

**Say where R differs rather than approximate.** R's defaults are not
statsmodels': ``confint`` on a glm is a profile-likelihood interval where
statsmodels reports a Wald one, ``tseries::adf.test`` interpolates its p-value
from a small table where statsmodels evaluates MacKinnon's polynomial,
``stats::arima`` optimizes CSS-ML where statsmodels runs an exact state-space
likelihood. Each of those is called out beside the line it affects, and where R
has no equivalent at all the comment says so instead of substituting something
close. An export that quietly answers a slightly different question is worse
than one that admits the gap.

**Nothing here was executed.** The Python export is tested by running it and
comparing every number with the pipeline's own. R is tested that way too when
``Rscript`` is on PATH; where it is not, these blocks rest on the documented
behaviour of each function, which is why the comments name the argument that
makes R agree rather than leaving the default in place.
"""

from __future__ import annotations

from typing import Any

from app.services.analysis_codegen_python_models import (
    DEFAULT_TAU,
    MAX_DIFFERENCES,
    MAX_LAG_FRACTION,
    MAX_LAGS,
    ODDS_RATIO,
    P_VALUE_FLOOR,
    RATE_RATIO,
    SEASONAL_PERIODS,
    STL_MIN_CYCLES,
    STL_SEASONAL_CYCLES,
)
from app.services.analysis_codegen_r import (
    ALPHA,
    CONFIDENCE_LEVEL,
    DATA,
    Lines,
    r_literal,
    register,
    register_helper,
)

# The two-sided quantile behind every interval below.
_LEVEL = r_literal(CONFIDENCE_LEVEL)
_TAIL = r_literal(round((1 + CONFIDENCE_LEVEL) / 2, 10))

# R's names for the period a frequency implies, used by cut() and seq().
_R_UNITS = {"D": "day", "W": "week", "ME": "month", "QE": "quarter", "YE": "year"}


# ---------------------------------------------------------------------------
# Helpers emitted into the script
# ---------------------------------------------------------------------------

REGRESSION_FRAME = register_helper(
    "regression_frame",
    """regression_frame <- function(frame, outcome, regressors, also_required = character(0),
                             numeric_outcome = TRUE) {
  # The rows and columns the model was actually fitted on.
  #
  # Two choices here decide every coefficient. Rows missing the outcome or any
  # regressor are dropped listwise and nothing is imputed. A categorical
  # regressor is coded against its ALPHABETICALLY FIRST level, so the baseline
  # is a property of the data rather than of row order in the upload.
  #
  # The fitted frame uses generated names (y_, t1_, t2_ ...) because a formula
  # needs syntactic identifiers and an uploaded column name is not one. The
  # product's own term names come back in $terms and are put on the coefficient
  # table by coefficient_table().
  used <- unique(c(outcome, regressors, also_required))
  working <- frame[, used, drop = FALSE]
  if (numeric_outcome) working[[outcome]] <- num(working[[outcome]])
  working <- working[stats::complete.cases(working), , drop = FALSE]

  columns <- list()
  labels <- character(0)
  references <- list()
  for (name in regressors) {
    values <- working[[name]]
    if (is.numeric(values) || is.logical(values)) {
      columns[[length(columns) + 1]] <- as.numeric(values)
      labels <- c(labels, name)
      next
    }
    as_text <- as.character(values)
    present <- sort(unique(as_text))
    references[[name]] <- present[1]
    for (level in present[-1]) {
      columns[[length(columns) + 1]] <- as.numeric(as_text == level)
      labels <- c(labels, sprintf("%s[%s]", name, level))
    }
  }
  names(columns) <- paste0("t", seq_along(columns), "_")
  fitted <- as.data.frame(columns, stringsAsFactors = FALSE)
  fitted$y_ <- if (numeric_outcome) as.numeric(working[[outcome]]) else NA_real_
  list(rows = working, data = fitted, terms = labels, references = references)
}""",
)

R_COEFFICIENT_TABLE = register_helper(
    "coefficient_table",
    f"""coefficient_table <- function(estimates, bounds, terms, statistic, ratio = NULL) {{
  # estimate, standard error, statistic, p-value and a {CONFIDENCE_LEVEL:.0%} interval per term.
  # `ratio` names three columns for the exponentiated view: an odds ratio in a
  # logit, an incidence rate ratio in a count model. exp() is clipped rather
  # than allowed to overflow, so a separated term saturates instead of Inf.
  out <- data.frame(
    term = c("(Intercept)", terms),
    coefficient = unname(estimates[, 1]),
    std_err = unname(estimates[, 2]),
    stat = unname(estimates[, 3]),
    # A p-value that underflows to 0 is not zero; it is below what a double can
    # represent, and printing 0 claims a certainty no test supports.
    p_value = pmax(unname(estimates[, 4]), {r_literal(P_VALUE_FLOOR)}),
    ci_low = unname(bounds[, 1]),
    ci_high = unname(bounds[, 2]),
    stringsAsFactors = FALSE
  )
  names(out)[4] <- statistic
  if (!is.null(ratio)) {{
    clipped <- function(v) exp(pmin(pmax(v, -709), 709))
    out[[ratio[1]]] <- clipped(out$coefficient)
    out[[ratio[2]]] <- clipped(out$ci_low)
    out[[ratio[3]]] <- clipped(out$ci_high)
  }}
  out
}}""",
)

R_SUCCESS = register_helper(
    "success_indicator",
    """success_indicator <- function(values, success) {
  # 1 where the outcome equals `success`, compared as text and then as number.
  # Comparing "1" against a numeric column of 1 as text alone would match
  # nothing, and a base rate of zero reads as a finding rather than a typo.
  matched <- as.character(values) == as.character(success)
  if (!any(matched, na.rm = TRUE)) {
    numeric_success <- suppressWarnings(as.numeric(success))
    if (!is.na(numeric_success)) matched <- num(values) == numeric_success
  }
  as.numeric(matched)
}""",
)

R_SERIES_GRID = register_helper(
    "series_grid",
    """series_grid <- function(frame, date_column, value_columns, freq, agg = "mean") {
  # The regular grid every time-series operation is fitted on.
  #
  # Uploaded data is essentially never regularly spaced and every method below
  # assumes it is. Rows missing the date or any value are dropped, observations
  # sharing a period are collapsed by `agg`, and periods with no observation are
  # filled by linear interpolation across the time axis — a forward fill would
  # fabricate a flat stretch and bias every variance and autocorrelation down.
  # The filled points are estimates, not measurements, and the count is printed.
  #
  # Two labelling differences from the product, neither of which changes a
  # value: pandas labels each period by its END and cut() by its start, and a
  # pandas week ends on Sunday where cut(breaks = "week") starts one on Monday.
  units <- c(D = "day", W = "week", ME = "month", QE = "quarter", YE = "year")
  unit <- unname(units[freq])

  working <- data.frame(period = as.Date(frame[[date_column]]))
  for (name in value_columns) working[[name]] <- num(frame[[name]])
  working <- working[stats::complete.cases(working), , drop = FALSE]
  working <- working[order(working$period), , drop = FALSE]
  working$period <- as.Date(cut(working$period, breaks = unit))

  collapsed <- stats::aggregate(
    working[value_columns], by = list(period = working$period), FUN = agg
  )
  full <- data.frame(
    period = seq(min(collapsed$period), max(collapsed$period), by = unit)
  )
  merged <- merge(full, collapsed, by = "period", all.x = TRUE)
  empty <- sum(!stats::complete.cases(merged[value_columns]))
  axis <- as.numeric(merged$period)
  for (name in value_columns) {
    # rule = 2 holds the end values flat, as the product's ffill/bfill does.
    merged[[name]] <- stats::approx(axis, merged[[name]], xout = axis, rule = 2)$y
  }
  list(data = merged, freq = freq, unit = unit, interpolated = empty)
}""",
)

R_BARTLETT = register_helper(
    "bartlett_band",
    f"""bartlett_band <- function(values, correlations, lags) {{
  # Bartlett {CONFIDENCE_LEVEL:.0%} bands, which widen with the lag because each estimate is
  # conditional on the ones before it. R's own acf() plot draws the FLAT
  # +/- 1.96/sqrt(n) white-noise band instead, which is too narrow past lag 1,
  # so the band the product reports is computed here rather than read off acf().
  n <- length(values)
  variance <- rep(1 / n, lags + 1)
  variance[1] <- 0
  if (lags >= 2) {{
    variance[3:(lags + 1)] <- variance[3:(lags + 1)] *
      (1 + 2 * cumsum(correlations[2:lags]^2))
  }}
  qnorm({_TAIL}) * sqrt(variance)
}}""",
)

R_SURVEY_FRAME = register_helper(
    "survey_frame",
    """survey_frame <- function(frame, weights, value = NULL, group = NULL, row = NULL,
                         col = NULL, strata = NULL, cluster = NULL, fpc = NULL,
                         domain = NULL, domain_value = NULL) {
  # The rows a weighted estimate may use, under generated names svydesign can
  # put in a formula. Listwise: a row missing the analysis variable, the weight
  # or any design or grouping label has nowhere to go. A zero weight removes the
  # respondent from the estimated population entirely, so those rows go too —
  # and dropping a row whose weight is MISSING biases the estimate, because it
  # leaves the population being described and the remaining weights are not
  # recalibrated to stand in for it.
  out <- data.frame(w_ = num(frame[[weights]]), stringsAsFactors = FALSE)
  if (!is.null(value)) out$y_ <- num(frame[[value]])
  if (length(group)) {
    out$g_ <- apply(
      as.data.frame(lapply(frame[group], as.character), stringsAsFactors = FALSE),
      1, paste, collapse = " / "
    )
  }
  if (!is.null(row)) out$row_ <- as.character(frame[[row]])
  if (!is.null(col)) out$col_ <- as.character(frame[[col]])
  if (!is.null(domain)) out$dom_ <- as.character(frame[[domain]]) == domain_value
  out$s_ <- if (is.null(strata)) "1" else as.character(frame[[strata]])
  out$psu_ <- if (is.null(cluster)) as.character(seq_len(nrow(out))) else
    as.character(frame[[cluster]])
  if (!is.null(fpc)) out$fpc_ <- fpc
  out <- out[stats::complete.cases(out), , drop = FALSE]
  out[out$w_ > 0, , drop = FALSE]
}""",
)

R_SURVEY_ROWS = register_helper(
    "survey_rows",
    f"""survey_rows <- function(labels, estimates, errors, counts, weight_sums, unweighted,
                        dof, value_key) {{
  # One row per domain, with the estimate at index 2: the product plots the
  # second column, so a sample size there would put group sizes under a title
  # promising means. The interval is a t interval on the DESIGN degrees of
  # freedom (PSUs minus strata), not a normal one — which is what
  # confint.svystat gives by default, and why df = degf(design) is passed below.
  margin <- qt({_TAIL}, dof) * errors
  out <- data.frame(
    label = labels,
    value = estimates,
    unweighted = unweighted,
    n = counts,
    sum_of_weights = weight_sums,
    standard_error = errors,
    ci95_low = estimates - margin,
    ci95_high = estimates + margin,
    # Relative standard error: the usual publication threshold for "too noisy".
    relative_se = ifelse(estimates == 0, NA_real_, abs(errors / estimates)),
    stringsAsFactors = FALSE
  )
  names(out)[2] <- value_key
  names(out)[3] <- if (value_key == "weighted_mean") "unweighted_mean" else "unweighted_sum"
  out
}}""",
)


# ---------------------------------------------------------------------------
# Shared emitter pieces
# ---------------------------------------------------------------------------


def _model_lines(params: dict[str, Any], index: int, *, numeric_outcome: bool = True) -> Lines:
    """The listwise-deleted frame and the coded design, under generated names."""
    also = [params["exposure"]] if params.get("exposure") else []
    arguments = [
        f"{DATA}, {r_literal(params['y'])}, {r_literal(list(params['x']))}",
    ]
    if also:
        arguments.append(f"also_required = {r_literal(also)}")
    if not numeric_outcome:
        arguments.append("numeric_outcome = FALSE")
    return [
        "# The product refuses a design it cannot support — a constant regressor,",
        "# perfect collinearity, an outcome that is an exact function of its own",
        "# regressors — before fitting. This analysis passed those guards.",
        f"model_{index} <- regression_frame({', '.join(arguments)})",
        f"if (length(model_{index}$references)) {{",
        f'  cat("Categorical baselines:", paste(names(model_{index}$references),',
        f'      unlist(model_{index}$references), sep = " = ", collapse = "; "), "\\n")',
        "}",
    ]


def _focal_lines(index: int) -> Lines:
    return [
        "# The headline interval describes the first term of the first regressor the",
        "# question named; every other term's interval is in the table.",
        f"focal_{index} <- result_{index}[2, ]",
    ]


def _robust(params: dict[str, Any], default: str) -> str | None:
    choice = str(params.get("robust", default))
    return None if choice == "none" else choice


def _grid_lines(params: dict[str, Any], index: int, columns: list[str]) -> Lines:
    freq = params.get("freq")
    agg = str(params.get("agg", "mean"))
    lines: Lines = []
    if freq is None:
        lines += [
            "# The product infers the frequency from the spacing of the timestamps when",
            "# the spec does not name one. That inference is not reproduced here, so the",
            "# frequency it settled on is written into the call; change it and every",
            "# number below changes with it.",
        ]
    return lines + [
        f"grid_{index} <- series_grid(",
        f"  {DATA}, {r_literal(params['date'])}, {r_literal(columns)},",
        f"  freq = {r_literal(freq or 'ME')}, agg = {r_literal(agg)}",
        ")",
        'cat(sprintf("%d periods on a %s grid, %d of them interpolated.\\n",',
        f"  nrow(grid_{index}$data), grid_{index}$freq, grid_{index}$interpolated))",
    ]


def _period_lines(params: dict[str, Any], index: int) -> Lines:
    declared = params.get("seasonal_period")
    if declared is not None:
        return [f"period_{index} <- {r_literal(int(declared))}"]
    pairs = ", ".join(f"{key} = {value}" for key, value in SEASONAL_PERIODS.items())
    return [
        "# The cycle the frequency implies. Yearly data has none shorter than one",
        "# observation, which is why the product requires it to be stated there.",
        f"period_{index} <- unname(c({pairs})[grid_{index}$freq])",
    ]


# ---------------------------------------------------------------------------
# Tier 4 — regression
# ---------------------------------------------------------------------------


@register("ols", REGRESSION_FRAME, R_COEFFICIENT_TABLE, packages=("lmtest", "sandwich"))
def _emit_r_ols(params: dict[str, Any], label: str, index: int) -> Lines:
    robust = _robust(params, "HC3")
    if robust:
        estimates = [
            f"vcov_{index} <- sandwich::vcovHC(fit_{index}, type = {r_literal(robust)})",
            "# coeftest/coefci keep the t distribution on the residual degrees of",
            "# freedom, which is what the product asked statsmodels for with use_t=True;",
            "# statsmodels otherwise switches silently to the normal under a robust",
            "# covariance and labels a z as a t.",
            f"estimates_{index} <- lmtest::coeftest(fit_{index}, vcov. = vcov_{index})",
            f"bounds_{index} <- lmtest::coefci(",
            f"  fit_{index}, vcov. = vcov_{index}, level = {_LEVEL}",
            ")",
        ]
    else:
        estimates = [
            f"estimates_{index} <- summary(fit_{index})$coefficients",
            f"bounds_{index} <- confint(fit_{index}, level = {_LEVEL})",
        ]
    return [
        *_model_lines(params, index),
        f"fit_{index} <- lm(y_ ~ ., data = model_{index}$data)",
        *estimates,
        f"result_{index} <- coefficient_table(",
        f'  estimates_{index}, bounds_{index}, model_{index}$terms, "t"',
        ")",
        f"summary_{index} <- summary(fit_{index})",
        f"residuals_{index} <- as.numeric(residuals(fit_{index}))",
        f"ss_residual_{index} <- sum(residuals_{index}^2)",
        *_focal_lines(index),
        f"stats_{index} <- list(",
        f"  standard_errors = {r_literal(robust or 'classical')},",
        f"  n = nrow(model_{index}$data),",
        f"  n_excluded = nrow({DATA}) - nrow(model_{index}$data),",
        f"  df_model = summary_{index}$fstatistic[[2]],",
        f"  df_resid = fit_{index}$df.residual,",
        f"  r_squared = summary_{index}$r.squared,",
        f"  adj_r_squared = summary_{index}$adj.r.squared,",
        "  # F and its p-value come from the CLASSICAL fit whichever covariance was",
        "  # asked for, exactly as statsmodels reports them; lmtest::waldtest() with",
        "  # the same vcov. is the robust analogue, and is a different number.",
        f"  f_statistic = summary_{index}$fstatistic[[1]],",
        "  f_p_value = pf(",
        f"    summary_{index}$fstatistic[[1]], summary_{index}$fstatistic[[2]],",
        f"    summary_{index}$fstatistic[[3]], lower.tail = FALSE",
        "  ),",
        f"  rmse = sqrt(ss_residual_{index} / nrow(model_{index}$data)),",
        f"  residual_std_error = sqrt(ss_residual_{index} / fit_{index}$df.residual),",
        f"  aic = AIC(fit_{index}),",
        f"  bic = BIC(fit_{index}),",
        f"  ci95_low = focal_{index}$ci_low,",
        f"  ci95_high = focal_{index}$ci_high,",
        f"  effect_size = summary_{index}$r.squared,",
        "  # The diagnostics the product reports as assumption checks. Base R has",
        "  # neither, so both come from lmtest.",
        f"  durbin_watson = unname(lmtest::dwtest(fit_{index})$statistic),",
        f"  breusch_pagan_p = unname(lmtest::bptest(fit_{index})$p.value)",
        ")",
        "# AIC/BIC agree with statsmodels for a Gaussian likelihood; R counts the",
        "# residual variance as a parameter and so does statsmodels' OLS.",
        "# There is no Jarque-Bera in base R: use tseries::jarque.bera.test(residuals).",
        "# There is no VIF either: use car::vif(fit), which needs a named-column fit.",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("logit", REGRESSION_FRAME, R_COEFFICIENT_TABLE, R_SUCCESS)
def _emit_r_logit(params: dict[str, Any], label: str, index: int) -> Lines:
    robust = _robust(params, "none")
    lines = [
        *_model_lines(params, index, numeric_outcome=False),
        f"model_{index}$data$y_ <- success_indicator(",
        f"  model_{index}$rows[[{r_literal(params['y'])}]], {r_literal(params['success_value'])}",
        ")",
        f"successes_{index} <- sum(model_{index}$data$y_)",
        f"fit_{index} <- glm(y_ ~ ., data = model_{index}$data, family = binomial())",
    ]
    if robust:
        lines += [
            "# statsmodels applies the same White sandwich to every HC variant on a",
            "# maximum-likelihood fit, so HC0 through HC3 are one estimator here.",
            f"vcov_{index} <- sandwich::vcovHC(fit_{index}, type = {r_literal(robust)})",
            f"estimates_{index} <- lmtest::coeftest(fit_{index}, vcov. = vcov_{index})",
            f"bounds_{index} <- lmtest::coefci(",
            f"  fit_{index}, vcov. = vcov_{index}, level = {_LEVEL}, df = Inf",
            ")",
        ]
    else:
        lines += [
            "# confint.default() is the WALD interval, which is what statsmodels",
            "# reports. Plain confint() on a glm is a profile-likelihood interval — a",
            "# better interval, and a different number from the one the product printed.",
            f"estimates_{index} <- summary(fit_{index})$coefficients",
            f"bounds_{index} <- confint.default(fit_{index}, level = {_LEVEL})",
        ]
    return lines + [
        "# Odds ratios are exp(coefficient), and their interval is exp of the",
        "# coefficient's interval — not a symmetric interval around the ratio.",
        f"result_{index} <- coefficient_table(",
        f'  estimates_{index}, bounds_{index}, model_{index}$terms, "z",',
        f"  ratio = {r_literal(list(ODDS_RATIO))}",
        ")",
        f"null_{index} <- glm(y_ ~ 1, data = model_{index}$data, family = binomial())",
        *_focal_lines(index),
        f"stats_{index} <- list(",
        f"  n = nrow(model_{index}$data),",
        f"  n_excluded = nrow({DATA}) - nrow(model_{index}$data),",
        f"  successes = successes_{index},",
        f"  base_rate = successes_{index} / nrow(model_{index}$data),",
        f"  log_likelihood = as.numeric(logLik(fit_{index})),",
        f"  null_log_likelihood = as.numeric(logLik(null_{index})),",
        "  # McFadden's: not a share of variance, and small values are normal.",
        f"  pseudo_r_squared = 1 - as.numeric(logLik(fit_{index}))"
        f" / as.numeric(logLik(null_{index})),",
        f"  llr_statistic = null_{index}$deviance - fit_{index}$deviance,",
        "  llr_p_value = pchisq(",
        f"    null_{index}$deviance - fit_{index}$deviance,",
        f"    null_{index}$df.residual - fit_{index}$df.residual, lower.tail = FALSE",
        "  ),",
        f"  aic = AIC(fit_{index}),",
        f"  bic = BIC(fit_{index}),",
        f"  ci95_low = focal_{index}${ODDS_RATIO[1]},",
        f"  ci95_high = focal_{index}${ODDS_RATIO[2]},",
        "  # Chinn's conversion: a log-odds ratio divided by pi/sqrt(3) — the standard",
        "  # deviation of the logistic — is on Cohen's d scale.",
        f"  effect_size = focal_{index}$coefficient * sqrt(3) / pi",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("count_model", REGRESSION_FRAME, R_COEFFICIENT_TABLE, packages=("MASS",))
def _emit_r_count_model(params: dict[str, Any], label: str, index: int) -> Lines:
    family = str(params.get("family", "poisson"))
    offset = (
        f"offset = log(model_{index}$rows[[{r_literal(params['exposure'])}]]), "
        if params.get("exposure")
        else ""
    )
    if family == "poisson":
        fit = [
            f"fit_{index} <- glm(",
            f"  y_ ~ ., data = model_{index}$data, {offset}family = poisson()",
            ")",
            f"null_{index} <- glm(",
            f"  y_ ~ 1, data = model_{index}$data, {offset}family = poisson()",
            ")",
            "# Pearson chi-square over residual df: near 1 is what Poisson assumes,",
            "# well above 1 means every p-value beside these coefficients is optimistic.",
            f'chi_square_{index} <- sum(residuals(fit_{index}, type = "pearson")^2)',
        ]
    else:
        fit = [
            "# MASS is not attached because it masks dplyr::select; glm.nb is called",
            "# with its namespace instead. MASS estimates theta = 1 / alpha, where alpha",
            "# is the NB2 overdispersion parameter statsmodels reports — the same model,",
            "# a reciprocal parameterisation, and a different number in the output.",
            f"fit_{index} <- MASS::glm.nb(",
            f"  y_ ~ ., data = model_{index}$data{', ' + offset.rstrip(', ') if offset else ''}",
            ")",
            f"null_{index} <- MASS::glm.nb(",
            f"  y_ ~ 1, data = model_{index}$data{', ' + offset.rstrip(', ') if offset else ''}",
            ")",
            f'chi_square_{index} <- sum(residuals(fit_{index}, type = "pearson")^2)',
        ]
    return [
        *_model_lines(params, index),
        *fit,
        "# confint.default() is the Wald interval statsmodels reports; plain confint()",
        "# on a glm is a profile-likelihood interval and a different number.",
        f"estimates_{index} <- summary(fit_{index})$coefficients",
        f"bounds_{index} <- confint.default(fit_{index}, level = {_LEVEL})",
        f"result_{index} <- coefficient_table(",
        f'  estimates_{index}, bounds_{index}, model_{index}$terms, "z",',
        f"  ratio = {r_literal(list(RATE_RATIO))}",
        ")",
        *_focal_lines(index),
        f"stats_{index} <- list(",
        f"  family = {r_literal(family)},",
        f"  n = nrow(model_{index}$data),",
        f"  n_excluded = nrow({DATA}) - nrow(model_{index}$data),",
        f"  df_resid = fit_{index}$df.residual,",
        f"  mean_outcome = mean(model_{index}$data$y_),",
        f"  variance_outcome = var(model_{index}$data$y_),",
        f"  log_likelihood = as.numeric(logLik(fit_{index})),",
        f"  null_log_likelihood = as.numeric(logLik(null_{index})),",
        f"  pseudo_r_squared = 1 - as.numeric(logLik(fit_{index}))"
        f" / as.numeric(logLik(null_{index})),",
        f"  aic = AIC(fit_{index}),",
        f"  bic = BIC(fit_{index}),",
        f"  pearson_chi2 = chi_square_{index},",
        f"  dispersion_ratio = chi_square_{index} / fit_{index}$df.residual,",
        "  dispersion_p_value = pchisq(",
        f"    chi_square_{index}, fit_{index}$df.residual, lower.tail = FALSE",
        "  ),",
        f"  ci95_low = focal_{index}${RATE_RATIO[1]},",
        f"  ci95_high = focal_{index}${RATE_RATIO[2]},",
        "  # The incidence rate ratio: the multiplicative change in the expected",
        "  # count. It has no conventional magnitude scale; 1.0 is no effect.",
        f"  effect_size = focal_{index}${RATE_RATIO[0]}",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("quantile_regression", REGRESSION_FRAME, R_COEFFICIENT_TABLE, packages=("quantreg",))
def _emit_r_quantile_regression(params: dict[str, Any], label: str, index: int) -> Lines:
    tau = float(params.get("tau", DEFAULT_TAU))
    return [
        *_model_lines(params, index),
        "# Each coefficient is the change in this quantile of the outcome per unit of",
        "# the regressor — a different question from the change in its mean.",
        f"fit_{index} <- quantreg::rq(y_ ~ ., data = model_{index}$data, tau = {r_literal(tau)})",
        '# se = "nid" is quantreg\'s Hendricks-Koenker sandwich, the closest analogue of',
        "# the Huber sandwich statsmodels' QuantReg uses by default. The two choose",
        "# their bandwidth by different rules, so the standard errors — and only the",
        "# standard errors — can differ in the last digits. The coefficients agree.",
        f'estimates_{index} <- summary(fit_{index}, se = "nid")$coefficients',
        "# quantreg reports no interval with this summary, so it is built the way",
        "# statsmodels does: estimate +/- t(df residual) * standard error.",
        f"margin_{index} <- qt({_TAIL}, fit_{index}$rho * 0 +",
        f"  nrow(model_{index}$data) - length(coef(fit_{index}))) * estimates_{index}[, 2]",
        f"bounds_{index} <- cbind(",
        f"  estimates_{index}[, 1] - margin_{index}, estimates_{index}[, 1] + margin_{index}",
        ")",
        f"result_{index} <- coefficient_table(",
        f'  estimates_{index}, bounds_{index}, model_{index}$terms, "t"',
        ")",
        *_focal_lines(index),
        "# Koenker-Machado pseudo R-squared: goodness of fit at this quantile only.",
        f"null_{index} <- quantreg::rq(",
        f"  y_ ~ 1, data = model_{index}$data, tau = {r_literal(tau)}",
        ")",
        f"stats_{index} <- list(",
        f"  tau = {r_literal(tau)},",
        f"  n = nrow(model_{index}$data),",
        f"  n_excluded = nrow({DATA}) - nrow(model_{index}$data),",
        f"  pseudo_r_squared = 1 - fit_{index}$rho / null_{index}$rho,",
        f"  share_below_fit = mean(residuals(fit_{index}) < 0),",
        f"  ci95_low = focal_{index}$ci_low,",
        f"  ci95_high = focal_{index}$ci_high,",
        f"  effect_size = 1 - fit_{index}$rho / null_{index}$rho",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 5 — time series
# ---------------------------------------------------------------------------


@register("decompose", R_SERIES_GRID)
def _emit_r_decompose(params: dict[str, Any], label: str, index: int) -> Lines:
    column = r_literal(params["value"])
    return [
        *_grid_lines(params, index, [params["value"]]),
        *_period_lines(params, index),
        f"values_{index} <- grid_{index}$data[[{column}]]",
        f"series_{index} <- ts(values_{index}, frequency = period_{index})",
        "# STL estimates a seasonal component that evolves, which needs more history",
        "# than the classical fixed-seasonal average; below three cycles it is the",
        "# classical method or nothing.",
        f"if (length(series_{index}) >= {STL_MIN_CYCLES} * period_{index}) {{",
        "  # A locally-constant seasonal smoother spanning two cycles. The default of",
        "  # 7 fits noise into the seasonal component: on white noise the usual",
        "  # seasonal-strength measure comes out near 0.4 rather than near 0.",
        f"  window_{index} <- {STL_SEASONAL_CYCLES} * period_{index} + 1",
        f"  window_{index} <- max(7, ifelse(window_{index} %% 2 == 1,"
        f" window_{index}, window_{index} + 1))",
        "  # stats::stl and statsmodels' STL are two implementations of the same",
        "  # Cleveland algorithm and agree closely rather than exactly; the trend and",
        "  # low-pass windows are left at their defaults in both.",
        f"  fitted_{index} <- stl(",
        f"    series_{index}, s.window = window_{index}, s.degree = 0, robust = FALSE",
        "  )",
        f'  trend_{index} <- as.numeric(fitted_{index}$time.series[, "trend"])',
        f'  seasonal_{index} <- as.numeric(fitted_{index}$time.series[, "seasonal"])',
        f'  residual_{index} <- as.numeric(fitted_{index}$time.series[, "remainder"])',
        f'  method_{index} <- sprintf("STL (LOESS, seasonal window %d)", window_{index})',
        "} else {",
        f'  fitted_{index} <- decompose(series_{index}, type = "additive")',
        f"  trend_{index} <- as.numeric(fitted_{index}$trend)",
        f"  seasonal_{index} <- as.numeric(fitted_{index}$seasonal)",
        f"  residual_{index} <- as.numeric(fitted_{index}$random)",
        f'  method_{index} <- "classical additive decomposition"',
        "}",
        f"result_{index} <- data.frame(",
        f"  date = grid_{index}$data$period,",
        f"  observed = values_{index},",
        f"  trend = trend_{index},",
        f"  seasonal = seasonal_{index},",
        f"  residual = residual_{index},",
        "  stringsAsFactors = FALSE",
        ")",
        "# Strength on [0, 1]: 1 - Var(remainder) / Var(remainder + component). It",
        "# describes this decomposition; it is not a test.",
        f"strength_{index} <- function(component) {{",
        f"  combined <- var(residual_{index} + component, na.rm = TRUE)",
        "  if (!is.finite(combined) || combined <= 0) return(NA_real_)",
        f"  min(1, max(0, 1 - var(residual_{index}, na.rm = TRUE) / combined))",
        "}",
        f"time_{index} <- seq_along(trend_{index})",
        f"slope_fit_{index} <- lm(trend_{index} ~ time_{index})",
        f"slope_ci_{index} <- confint(slope_fit_{index}, level = {_LEVEL})[2, ]",
        f"stats_{index} <- list(",
        f"  method = method_{index},",
        f"  seasonal_period = period_{index},",
        f"  periods = nrow(grid_{index}$data),",
        f"  periods_interpolated = grid_{index}$interpolated,",
        f"  trend_strength = strength_{index}(trend_{index}),",
        f"  seasonal_strength = strength_{index}(seasonal_{index}),",
        f"  trend_slope_per_period = unname(coef(slope_fit_{index})[2]),",
        f"  seasonal_amplitude = (max(seasonal_{index}) - min(seasonal_{index})) / 2,",
        f"  seasonal_peak_to_trough = max(seasonal_{index}) - min(seasonal_{index}),",
        f"  residual_sd = sd(residual_{index}, na.rm = TRUE),",
        f"  ci95_low = unname(slope_ci_{index}[1]),",
        f"  ci95_high = unname(slope_ci_{index}[2]),",
        f"  effect_size = strength_{index}(seasonal_{index})",
        ")",
        f"show_result({r_literal(label)}, head(result_{index}), stats_{index})",
    ]


@register("stationarity_test", R_SERIES_GRID, packages=("tseries", "urca"))
def _emit_r_stationarity_test(params: dict[str, Any], label: str, index: int) -> Lines:
    column = r_literal(params["value"])
    trend = str(params.get("regression", "c")) == "ct"
    return [
        *_grid_lines(params, index, [params["value"]]),
        f"values_{index} <- grid_{index}$data[[{column}]]",
        "# Two tests with OPPOSITE nulls. ADF's null is a unit root; KPSS's null is",
        "# stationarity. Their disagreement is the informative part: it separates a",
        "# unit root (difference it) from a deterministic trend (detrend it).",
        "#",
        "# ADF: urca::ur.df picks its lag by AIC, as the product asked statsmodels to.",
        "# It reports the statistic and MacKinnon's CRITICAL VALUES but no p-value.",
        "# tseries::adf.test does report one, from a small interpolated table that is",
        "# truncated at 0.01 and 0.99 and with a lag fixed at trunc((n-1)^(1/3)) — so",
        "# its p-value is NOT the MacKinnon polynomial value the product printed, and",
        "# comparing the statistic against the critical values below is the honest",
        "# check. There is no MacKinnon p-value in R.",
        f"adf_{index} <- urca::ur.df(",
        f'  values_{index}, type = {r_literal("trend" if trend else "drift")}, selectlags = "AIC"',
        ")",
        f"print(summary(adf_{index}))",
        "",
        "# KPSS: statsmodels chooses its lag by the data-dependent Hobijn rule",
        '# (nlags = "auto"); tseries uses trunc(4 * (n/100)^0.25) with lshort = TRUE.',
        "# Different lag, so a slightly different statistic. Its p-value comes from a",
        "# table truncated to [0.01, 0.1], which is the same bound the product reports.",
        f"kpss_{index} <- tseries::kpss.test(",
        f"  values_{index}, null = {r_literal('Trend' if trend else 'Level')}, lshort = TRUE",
        ")",
        f"result_{index} <- data.frame(",
        '  test = c("Augmented Dickey-Fuller", "KPSS"),',
        f"  statistic = c(adf_{index}@teststat[1], unname(kpss_{index}$statistic)),",
        f"  p_value = c(NA_real_, kpss_{index}$p.value),",
        f'  critical_1pct = c(adf_{index}@cval[1, "1pct"], NA_real_),',
        f'  critical_5pct = c(adf_{index}@cval[1, "5pct"], NA_real_),',
        f'  critical_10pct = c(adf_{index}@cval[1, "10pct"], NA_real_),',
        "  stringsAsFactors = FALSE",
        ")",
        "# How many differences it takes before ADF rejects a unit root. The product",
        "# decides this with the MacKinnon p-value, so R can reach a different answer",
        "# on a borderline series; compare the statistic with the 5% critical value.",
        f"working_{index} <- values_{index}",
        f"differences_{index} <- {MAX_DIFFERENCES + 1}",
        f"for (order in 0:{MAX_DIFFERENCES}) {{",
        f"  step <- urca::ur.df(working_{index}, type ="
        f' {r_literal("trend" if trend else "drift")}, selectlags = "AIC")',
        '  if (step@teststat[1] < step@cval[1, "5pct"]) {',
        f"    differences_{index} <- order",
        "    break",
        "  }",
        f"  working_{index} <- diff(working_{index})",
        "}",
        "# Lag-1 autocorrelation with a Bartlett interval — how persistent the series is.",
        f"rho_{index} <- as.numeric(acf(values_{index}, lag.max = 1, plot = FALSE)$acf[2])",
        f"margin_{index} <- qnorm({_TAIL}) / sqrt(length(values_{index}))",
        f"stats_{index} <- list(",
        f"  periods = nrow(grid_{index}$data),",
        f"  adf_statistic = adf_{index}@teststat[1],",
        f"  kpss_statistic = unname(kpss_{index}$statistic),",
        f"  kpss_p_value = kpss_{index}$p.value,",
        f"  differences_suggested = differences_{index},",
        f"  effect_size = rho_{index},",
        f"  ci95_low = rho_{index} - margin_{index},",
        f"  ci95_high = rho_{index} + margin_{index}",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("autocorrelation", R_SERIES_GRID, R_BARTLETT)
def _emit_r_autocorrelation(params: dict[str, Any], label: str, index: int) -> Lines:
    column = r_literal(params["value"])
    requested = params.get("lags")
    wanted = (
        r_literal(int(requested))
        if requested is not None
        else f"max(1, round(10 * log10(max(length(values_{index}), 10))))"
    )
    return [
        *_grid_lines(params, index, [params["value"]]),
        f"values_{index} <- grid_{index}$data[[{column}]]",
        "# Autocorrelations past a quarter of the series rest on too few overlapping",
        "# pairs to mean anything, so the lag count is capped there.",
        f"ceiling_{index} <- max(1, min(floor(length(values_{index}) *"
        f" {r_literal(MAX_LAG_FRACTION)}), {MAX_LAGS}))",
        f"lags_{index} <- min({wanted}, ceiling_{index})",
        f"acf_{index} <- acf(values_{index}, lag.max = lags_{index}, plot = FALSE)$acf[, 1, 1]",
        f"pacf_{index} <- pacf(values_{index}, lag.max = lags_{index}, plot = FALSE)$acf[, 1, 1]",
        f"acf_margin_{index} <- bartlett_band(values_{index}, acf_{index}, lags_{index})",
        "# The PACF band is the flat one in both: each partial autocorrelation has",
        "# variance 1/n under the null that the series is white noise.",
        f"pacf_margin_{index} <- qnorm({_TAIL}) / sqrt(length(values_{index}))",
        f"lag_{index} <- seq_len(lags_{index})",
        f"acf_low_{index} <- acf_{index}[lag_{index} + 1] - acf_margin_{index}[lag_{index} + 1]",
        f"acf_high_{index} <- acf_{index}[lag_{index} + 1] + acf_margin_{index}[lag_{index} + 1]",
        f"pacf_low_{index} <- pacf_{index}[lag_{index}] - pacf_margin_{index}",
        f"pacf_high_{index} <- pacf_{index}[lag_{index}] + pacf_margin_{index}",
        f"result_{index} <- data.frame(",
        f"  lag = lag_{index},",
        f"  acf = acf_{index}[lag_{index} + 1],",
        f"  acf_ci95_low = acf_low_{index},",
        f"  acf_ci95_high = acf_high_{index},",
        f"  acf_outside_band = acf_low_{index} > 0 | acf_high_{index} < 0,",
        f"  pacf = pacf_{index}[lag_{index}],",
        f"  pacf_ci95_low = pacf_low_{index},",
        f"  pacf_ci95_high = pacf_high_{index},",
        f"  pacf_outside_band = pacf_low_{index} > 0 | pacf_high_{index} < 0,",
        "  stringsAsFactors = FALSE",
        ")",
        "# The product holds the Ljung-Box lag count to a fifth of the series, so a",
        "# joint test over more lags than the sample supports is not reported.",
        f"lb_lags_{index} <- min(lags_{index}, max(1, floor(length(values_{index}) / 5)))",
        f"lb_{index} <- Box.test(",
        f'  values_{index}, lag = lb_lags_{index}, type = "Ljung-Box"',
        ")",
        f"stats_{index} <- list(",
        f"  periods = nrow(grid_{index}$data),",
        f"  lags = lags_{index},",
        f"  ljung_box_statistic = unname(lb_{index}$statistic),",
        f"  ljung_box_dof = unname(lb_{index}$parameter),",
        f"  ljung_box_p_value = lb_{index}$p.value,",
        f"  effect_size = acf_{index}[2],",
        f"  ci95_low = acf_{index}[2] - acf_margin_{index}[2],",
        f"  ci95_high = acf_{index}[2] + acf_margin_{index}[2]",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


def _r_orders(params: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int, int]]:
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


@register("arima", R_SERIES_GRID)
def _emit_r_arima(params: dict[str, Any], label: str, index: int) -> Lines:
    column = r_literal(params["value"])
    order, seasonal = _r_orders(params)
    horizon = params.get("forecast_periods")
    frequency = seasonal[3] or 1
    lines = [
        *_grid_lines(params, index, [params["value"]]),
        f"values_{index} <- grid_{index}$data[[{column}]]",
        f"series_{index} <- ts(values_{index}, frequency = {frequency})",
        '# method = "ML" is the exact likelihood statsmodels maximises; stats::arima',
        '# defaults to "CSS-ML", which conditions the first observations away and gives',
        "# slightly different estimates. Even with ML the two optimisers stop in",
        "# different places, so expect agreement to a few decimal places rather than",
        "# to the last digit. forecast::Arima() wraps this with a tidier interface.",
        f"fit_{index} <- arima(",
        f"  series_{index}, order = c({', '.join(str(v) for v in order)}),",
        f"  seasonal = list(order = c({', '.join(str(v) for v in seasonal[:3])}),"
        f" period = {frequency}),",
        '  method = "ML"',
        ")",
        f"errors_{index} <- sqrt(diag(fit_{index}$var.coef))",
        f"z_{index} <- coef(fit_{index}) / errors_{index}",
        f"margin_{index} <- qnorm({_TAIL}) * errors_{index}",
        f"coefficients_{index} <- data.frame(",
        f"  term = names(coef(fit_{index})),",
        f"  coefficient = unname(coef(fit_{index})),",
        f"  std_error = unname(errors_{index}),",
        f"  z = unname(z_{index}),",
        f"  p_value = 2 * pnorm(abs(unname(z_{index})), lower.tail = FALSE),",
        f"  ci95_low = unname(coef(fit_{index}) - margin_{index}),",
        f"  ci95_high = unname(coef(fit_{index}) + margin_{index}),",
        "  stringsAsFactors = FALSE",
        ")",
        "# R names the intercept `intercept` and the AR/MA terms ar1, ma1; statsmodels",
        "# calls them const, ar.L1, ma.L1. The same coefficients, different labels.",
    ]
    if horizon is None:
        lines.append(f"result_{index} <- coefficients_{index}")
    else:
        lines += [
            "# A forecast is a claim about the future stated in the same typeface as a",
            "# measurement, so every forecast row is marked and carries its prediction",
            "# interval. The interval assumes THIS model is the right one; it does not",
            "# cover the risk that it is not, and it widens with each step ahead.",
            f"forecast_{index} <- predict(fit_{index}, n.ahead = {int(horizon)})",
            f"context_{index} <- min(3 * {int(horizon)}, 60, length(values_{index}))",
            f"tail_{index} <- tail(seq_along(values_{index}), context_{index})",
            f"result_{index} <- rbind(",
            "  data.frame(",
            f"    date = grid_{index}$data$period[tail_{index}],",
            f"    value = values_{index}[tail_{index}],",
            "    ci95_low = NA_real_, ci95_high = NA_real_,",
            '    kind = "observed", stringsAsFactors = FALSE',
            "  ),",
            "  data.frame(",
            "    date = seq(",
            f"      max(grid_{index}$data$period), by = grid_{index}$unit,"
            f" length.out = {int(horizon)} + 1",
            "    )[-1],",
            f"    value = as.numeric(forecast_{index}$pred),",
            f"    ci95_low = as.numeric(forecast_{index}$pred)"
            f" - qnorm({_TAIL}) * as.numeric(forecast_{index}$se),",
            f"    ci95_high = as.numeric(forecast_{index}$pred)"
            f" + qnorm({_TAIL}) * as.numeric(forecast_{index}$se),",
            '    kind = "forecast", stringsAsFactors = FALSE',
            "  )",
            ")",
        ]
    headline = "intercept" if not order[0] and not order[2] else ("ar1" if order[0] else "ma1")
    return lines + [
        f"position_{index} <- match({r_literal(headline)}, coefficients_{index}$term)",
        f"headline_{index} <- coefficients_{index}[",
        f"  if (is.na(position_{index})) 1 else position_{index},",
        "]",
        f"residual_{index} <- as.numeric(residuals(fit_{index}))",
        f"stats_{index} <- list(",
        f"  periods = nrow(grid_{index}$data),",
        f"  aic = AIC(fit_{index}),",
        f"  bic = BIC(fit_{index}),",
        f"  log_likelihood = as.numeric(logLik(fit_{index})),",
        f"  sigma2 = fit_{index}$sigma2,",
        f"  ci95_low = headline_{index}$ci95_low,",
        f"  ci95_high = headline_{index}$ci95_high,",
        "  # In-sample fit, not out-of-sample accuracy.",
        f"  effect_size = 1 - var(residual_{index}) / var(values_{index})",
        ")",
        "# There is no HQIC in base R: it is -2*logLik + 2*k*log(log(n)).",
        f"print(coefficients_{index})",
        f"show_result({r_literal(label)}, head(result_{index}), stats_{index})",
    ]


@register("granger_causality", R_SERIES_GRID, packages=("lmtest", "urca"))
def _emit_r_granger_causality(params: dict[str, Any], label: str, index: int) -> Lines:
    outcome, cause = params["value"], params["cause"]
    requested = params.get("max_lag")
    wanted = r_literal(int(requested)) if requested is not None else "4"
    return [
        "# Granger causality is predictive PRECEDENCE, not causation: it says past",
        "# values of the cause improve the forecast of the outcome, which is equally",
        "# consistent with a common driver, a reporting lag, or coincidence.",
        *_grid_lines(params, index, [outcome, cause]),
        f"pair_{index} <- data.frame(",
        f"  y_ = grid_{index}$data[[{r_literal(outcome)}]],",
        f"  x_ = grid_{index}$data[[{r_literal(cause)}]],",
        "  stringsAsFactors = FALSE",
        ")",
        "# Both series are differenced together — the same number of times whether or",
        "# not both needed it — because comparing lags of a level against lags of a",
        "# difference compares different quantities. A Granger test on non-stationary",
        "# series manufactures significance.",
        "#",
        "# The product makes this decision with statsmodels' MacKinnon p-value, which",
        "# R does not have; the 5% critical value from urca is the closest equivalent",
        "# and can differ on a borderline series. Check differences_applied below",
        "# against the number the product reported.",
        f"differences_{index} <- 0",
        f"for (order in 0:{MAX_DIFFERENCES}) {{",
        f"  stationary <- all(vapply(pair_{index}, function(column) {{",
        '    step <- urca::ur.df(column, type = "drift", selectlags = "AIC")',
        '    step@teststat[1] < step@cval[1, "5pct"]',
        "  }, logical(1)))",
        "  if (stationary) break",
        f"  pair_{index} <- as.data.frame(lapply(pair_{index}, diff))",
        f"  differences_{index} <- order + 1",
        "}",
        "# Lags are bounded so the unrestricted model keeps degrees of freedom.",
        f"ceiling_{index} <- max(1, min(floor(nrow(pair_{index}) *"
        f" {r_literal(MAX_LAG_FRACTION)}) %/% 2, {MAX_LAGS}))",
        f"max_lag_{index} <- min({wanted}, ceiling_{index})",
        f"rows_{index} <- do.call(rbind, lapply(seq_len(max_lag_{index}), function(lag) {{",
        f"  test <- lmtest::grangertest(y_ ~ x_, order = lag, data = pair_{index})",
        "  f_statistic <- test$F[2]",
        "  df_num <- abs(test$Df[2])",
        "  df_denom <- test$Res.Df[2]",
        "  data.frame(",
        "    lag = lag,",
        "    f_statistic = f_statistic,",
        "    df_num = df_num,",
        "    df_denom = df_denom,",
        '    p_value = test[["Pr(>F)"]][2],',
        "    # Partial eta squared: the share of the outcome's otherwise-unexplained",
        "    # variance that the lagged cause accounts for.",
        "    partial_eta_squared = f_statistic * df_num / (f_statistic * df_num + df_denom),",
        "    stringsAsFactors = FALSE",
        "  )",
        "}))",
        "# Testing several lags and reporting each at 0.05 is how a series is made to",
        "# look predictive; Benjamini-Hochberg adjusts for how many were tested.",
        f'rows_{index}$p_value_adjusted <- p.adjust(rows_{index}$p_value, method = "BH")',
        f'rows_{index}[["significant_at_0.05"]] <-'
        f" rows_{index}$p_value_adjusted < {r_literal(ALPHA)}",
        f"result_{index} <- rows_{index}",
        f"best_{index} <- result_{index}[which.min(result_{index}$p_value_adjusted), ]",
        "# The F-test says whether the lagged cause matters; the summed coefficient",
        "# says by how much and in which direction, which an F cannot.",
        f"lag_{index} <- best_{index}$lag",
        f"lagged_{index} <- cbind(",
        f"  sapply(1:lag_{index}, function(s)"
        f" head(c(rep(NA, s), pair_{index}$y_), nrow(pair_{index}))),",
        f"  sapply(1:lag_{index}, function(s)"
        f" head(c(rep(NA, s), pair_{index}$x_), nrow(pair_{index})))",
        ")",
        f"summed_{index} <- lm(pair_{index}$y_ ~ lagged_{index})",
        f"contrast_{index} <- c(0, rep(0, lag_{index}), rep(1, lag_{index}))",
        f"total_{index} <- sum(contrast_{index} * coef(summed_{index}))",
        f"variance_{index} <- as.numeric(",
        f"  t(contrast_{index}) %*% vcov(summed_{index}) %*% contrast_{index}",
        ")",
        f"margin_{index} <- qt({_TAIL}, summed_{index}$df.residual) * sqrt(variance_{index})",
        f"stats_{index} <- list(",
        f"  periods = nrow(pair_{index}),",
        f"  max_lag = max_lag_{index},",
        f"  differences_applied = differences_{index},",
        f"  best_lag = best_{index}$lag,",
        f"  effect_size = best_{index}$partial_eta_squared,",
        f"  ci95_low = total_{index} - margin_{index},",
        f"  ci95_high = total_{index} + margin_{index},",
        "  # Read p_value_adjusted, not p_value: several lags were tested.",
        '  adjustment = "Benjamini-Hochberg across the tested lags"',
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


# ---------------------------------------------------------------------------
# Tier 6 — survey estimation
# ---------------------------------------------------------------------------


def _survey_frame_lines(params: dict[str, Any], index: int, **roles: Any) -> Lines:
    """The usable rows under generated names, then the svydesign over them."""
    arguments = [f"{DATA}, {r_literal(params['weights'])}"]
    arguments += [f"{key} = {r_literal(value)}" for key, value in roles.items() if value]
    arguments += [
        f"strata = {r_literal(params.get('strata'))}",
        f"cluster = {r_literal(params.get('cluster'))}",
        f"fpc = {r_literal(params.get('fpc'))}",
    ]
    fpc = ", fpc = ~fpc_" if params.get("fpc") is not None else ""
    return [
        "# survey wants a formula per role, and a formula needs syntactic names, so",
        "# the columns are copied under generated ones first. s_ is a single constant",
        "# stratum and psu_ a distinct id per row where the spec declared neither,",
        "# which is exactly the design the product assumed.",
        f"sd_{index} <- survey_frame({', '.join(arguments)})",
        "# Refuse a single-PSU stratum rather than assigning it an arbitrary variance",
        "# contribution — the product refuses it by name.",
        'options(survey.lonely.psu = "fail")',
        f"design_{index} <- svydesign(",
        f"  ids = ~psu_, strata = ~s_, weights = ~w_{fpc}, data = sd_{index}, nest = TRUE",
        ")",
        f"dof_{index} <- degf(design_{index})",
    ]


def _group_column(params: dict[str, Any]) -> str:
    group_by = params.get("group_by")
    return " / ".join(group_by) if group_by else "measure"


def _weighted_estimate(params: dict[str, Any], label: str, index: int, *, of_total: bool) -> Lines:
    group_by = list(params.get("group_by") or [])
    call = "svytotal" if of_total else "svymean"
    value_key = "weighted_total" if of_total else "weighted_mean"
    unweighted = "sum" if of_total else "mean"
    if group_by:
        estimate = [
            f"by_{index} <- svyby(~y_, ~g_, design_{index}, {call})",
            f"labels_{index} <- as.character(by_{index}$g_)",
            f"estimates_{index} <- as.numeric(coef(by_{index}))",
            f"errors_{index} <- as.numeric(SE(by_{index}))",
            f"counts_{index} <- as.numeric(table(sd_{index}$g_)[labels_{index}])",
            f"weight_sums_{index} <- as.numeric(",
            f"  tapply(sd_{index}$w_, sd_{index}$g_, sum)[labels_{index}]",
            ")",
            f"unweighted_{index} <- as.numeric(",
            f"  tapply(sd_{index}$y_, sd_{index}$g_, {unweighted})[labels_{index}]",
            ")",
        ]
    else:
        estimate = [
            f"estimate_{index} <- {call}(~y_, design_{index})",
            f'labels_{index} <- "(all respondents)"',
            f"estimates_{index} <- as.numeric(coef(estimate_{index}))",
            f"errors_{index} <- as.numeric(SE(estimate_{index}))",
            f"counts_{index} <- nrow(sd_{index})",
            f"weight_sums_{index} <- sum(sd_{index}$w_)",
            f"unweighted_{index} <- {unweighted}(sd_{index}$y_)",
        ]
    return [
        *_survey_frame_lines(params, index, value=params["column"], group=group_by),
        *estimate,
        f"result_{index} <- survey_rows(",
        f"  labels_{index}, estimates_{index}, errors_{index}, counts_{index},",
        f"  weight_sums_{index}, unweighted_{index}, dof_{index}, {r_literal(value_key)}",
        ")",
        f"names(result_{index})[1] <- {r_literal(_group_column(params))}",
        f"stats_{index} <- list(",
        f"  n = nrow(sd_{index}),",
        f"  estimated_population = sum(sd_{index}$w_),",
        f"  degrees_of_freedom = dof_{index},",
        "  # How far weighting moved the answer, in standard deviations: the question",
        "  # a reader has the moment they see two means side by side.",
        f"  effect_size = (weighted.mean(sd_{index}$y_, sd_{index}$w_)"
        f" - mean(sd_{index}$y_)) / sd(sd_{index}$y_)",
        ")",
        f"if (length(labels_{index}) == 1) {{",
        f"  stats_{index}${value_key} <- estimates_{index}[1]",
        f"  stats_{index}$standard_error <- errors_{index}[1]",
        f"  stats_{index}$ci95_low <- result_{index}$ci95_low[1]",
        f"  stats_{index}$ci95_high <- result_{index}$ci95_high[1]",
        "}",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("weighted_mean", R_SURVEY_FRAME, R_SURVEY_ROWS, packages=("survey",))
def _emit_r_weighted_mean(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        "# An unweighted mean of a weighted survey is not an approximation of this",
        "# number; it is a different quantity — the people who answered rather than",
        "# the population they were sampled to represent. Both are reported.",
        *_weighted_estimate(params, label, index, of_total=False),
    ]


@register("weighted_total", R_SURVEY_FRAME, R_SURVEY_ROWS, packages=("survey",))
def _emit_r_weighted_total(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        "# This total is only as good as the weights' calibration: they sum to the",
        "# population size being claimed. If the weight column was not calibrated to a",
        "# real population count, only the relative pattern means anything.",
        *_weighted_estimate(params, label, index, of_total=True),
    ]


@register("design_effect", R_SURVEY_FRAME, packages=("survey",))
def _emit_r_design_effect(params: dict[str, Any], label: str, index: int) -> Lines:
    group_by = list(params.get("group_by") or [])
    grouping = f"sd_{index}$g_" if group_by else f'rep("(all respondents)", nrow(sd_{index}))'
    return [
        "# Kish's design effect comes from the weights alone; the design-based one is",
        "# this variable's actual design variance over what simple random sampling of",
        "# the same n would have given, so it also carries any clustering. They agree",
        "# when the weights are unrelated to the outcome and diverge when they are not.",
        *_survey_frame_lines(params, index, value=params["column"], group=group_by),
        f"groups_{index} <- {grouping}",
        f"result_{index} <- do.call(rbind, lapply(sort(unique(groups_{index})), function(name) {{",
        f"  inside <- groups_{index} == name",
        f"  weights <- sd_{index}$w_[inside]",
        "  n <- length(weights)",
        "  # DEFF_Kish = n * sum(w^2) / (sum w)^2 = 1 + CV^2, with the POPULATION sd,",
        "  # which is the one for which that identity holds exactly.",
        "  kish <- n * sum(weights^2) / sum(weights)^2",
        "  cv <- sqrt(mean((weights - mean(weights))^2)) / mean(weights)",
        f"  domain <- subset(design_{index}, inside)",
        "  estimate <- svymean(~y_, domain, deff = TRUE)",
        "  data.frame(",
        "    label = name,",
        "    effective_sample_size = n / kish,",
        "    n = n,",
        "    design_effect_kish = kish,",
        "    design_effect_design_based = as.numeric(deff(estimate)),",
        "    weight_cv = cv,",
        "    weight_min = min(weights),",
        "    weight_max = max(weights),",
        "    sum_of_weights = sum(weights),",
        "    weighted_mean = as.numeric(coef(estimate)),",
        f"    unweighted_mean = mean(sd_{index}$y_[inside]),",
        "    stringsAsFactors = FALSE",
        "  )",
        "}))",
        f"names(result_{index})[1] <- {r_literal(_group_column(params))}",
        "# svymean(deff = TRUE) compares against simple random sampling WITH",
        "# replacement, which is the comparison the product makes too.",
        f"overall_{index} <- svymean(~y_, design_{index}, deff = TRUE)",
        f"kish_{index} <- nrow(sd_{index}) * sum(sd_{index}$w_^2) / sum(sd_{index}$w_)^2",
        f"stats_{index} <- list(",
        f"  n = nrow(sd_{index}),",
        f"  design_effect_kish = kish_{index},",
        f"  design_effect_design_based = as.numeric(deff(overall_{index})),",
        f"  effective_sample_size = nrow(sd_{index}) / kish_{index},",
        f"  effective_sample_size_design_based ="
        f" nrow(sd_{index}) / as.numeric(deff(overall_{index})),",
        f"  weight_cv = sqrt(mean((sd_{index}$w_ - mean(sd_{index}$w_))^2)) / mean(sd_{index}$w_),",
        f"  weight_min = min(sd_{index}$w_),",
        f"  weight_max = max(sd_{index}$w_),",
        f"  sum_of_weights = sum(sd_{index}$w_),",
        f"  weighted_mean = as.numeric(coef(overall_{index})),",
        f"  unweighted_mean = mean(sd_{index}$y_),",
        f"  degrees_of_freedom = dof_{index},",
        f"  effect_size = (weighted.mean(sd_{index}$y_, sd_{index}$w_)"
        f" - mean(sd_{index}$y_)) / sd(sd_{index}$y_)",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("weighted_crosstab", R_SURVEY_FRAME, packages=("survey",))
def _emit_r_weighted_crosstab(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        "# The ordinary chi-square on weighted counts treats the sum of the weights as",
        "# if it were a count of independent observations, which is the commonest error",
        "# in published survey analysis. Both statistics are computed so the size of",
        "# that error is visible.",
        *_survey_frame_lines(params, index, row=params["row"], col=params["column"]),
        f"table_{index} <- svytable(~row_ + col_, design_{index})",
        f"result_{index} <- cbind(",
        "  setNames(",
        f"    data.frame(rownames(table_{index}), stringsAsFactors = FALSE),",
        f"    {r_literal(params['row'])}",
        "  ),",
        f"  as.data.frame.matrix(table_{index})",
        ")",
        '# statistic = "Chisq" is the FIRST-ORDER Rao-Scott correction: Pearson\'s X^2',
        "# rescaled by the mean generalized design effect and referred to a chi-square",
        "# on (r-1)(c-1) df, which is exactly what the product computed. svychisq's",
        '# default, statistic = "F", is the second-order (Rao-Scott F, Satterthwaite)',
        '# version, which the product does not implement — so use "Chisq" to compare.',
        f'corrected_{index} <- svychisq(~row_ + col_, design_{index}, statistic = "Chisq")',
        f"counts_{index} <- table(sd_{index}$row_, sd_{index}$col_)",
        "# The naive test: the same table of weighted counts handed to an ordinary",
        "# chi-square, with the correction turned off so it matches the product's.",
        f"naive_{index} <- suppressWarnings(chisq.test(table_{index}, correct = FALSE))",
        f"uncorrected_{index} <- suppressWarnings(chisq.test(counts_{index}, correct = FALSE))",
        f"n_{index} <- nrow(sd_{index})",
        f"stats_{index} <- list(",
        '  correction_type = "first-order Rao-Scott (mean generalized design effect)",',
        f"  statistic = unname(corrected_{index}$statistic),",
        f"  dof = unname(corrected_{index}$parameter[1]),",
        f"  p_value = corrected_{index}$p.value,",
        f"  naive_weighted_statistic = unname(naive_{index}$statistic),",
        f"  naive_weighted_p_value = naive_{index}$p.value,",
        f"  n_unweighted = n_{index},",
        f"  estimated_population = sum(table_{index}),",
        f"  degrees_of_freedom = dof_{index},",
        "  # Cramer's V from the statistic at the REAL sample size, not the sum of",
        "  # weights — an effect size computed on weighted counts is meaningless.",
        "  effect_size = sqrt(",
        f"    unname(uncorrected_{index}$statistic)",
        f"    / (n_{index} * min(nrow(counts_{index}) - 1, ncol(counts_{index}) - 1))",
        "  )",
        ")",
        "# svychisq does not expose the correction factor it divided by. The product",
        "# divided Pearson's X^2 at the unweighted n by exactly that factor, so the",
        "# ratio below is a CHECK on the two statistics rather than an independent",
        "# estimate: it equals the product's correction_factor when svychisq scales to",
        "# the same n, and a mismatch means it scaled to something else.",
        f"stats_{index}$correction_factor_check <-",
        f"  unname(uncorrected_{index}$statistic) / unname(corrected_{index}$statistic)",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]


@register("subpopulation_estimate", R_SURVEY_FRAME, R_SURVEY_ROWS, packages=("survey",))
def _emit_r_subpopulation_estimate(params: dict[str, Any], label: str, index: int) -> Lines:
    return [
        "# The two rows share a point estimate and differ in the standard error.",
        "# subset() on a survey design is DOMAIN estimation: it keeps every respondent",
        "# in the variance calculation and uses a 0/1 indicator, so the strata, the",
        "# PSUs and the degrees of freedom stay those of the full design. Rebuilding",
        "# the design from the filtered rows — the second row below — recomputes the",
        "# variance from a smaller design, and that is the wrong standard error: the",
        "# domain's sample size is random, not fixed.",
        *_survey_frame_lines(
            params,
            index,
            value=params["column"],
            domain=params["subpopulation"],
            domain_value=str(params["subpopulation_value"]),
        ),
        f"domain_{index} <- svymean(~y_, subset(design_{index}, dom_))",
        f"inside_{index} <- sd_{index}[sd_{index}$dom_, , drop = FALSE]",
        f"naive_design_{index} <- svydesign(",
        f"  ids = ~psu_, strata = ~s_, weights = ~w_, data = inside_{index}, nest = TRUE",
        ")",
        f"naive_{index} <- svymean(~y_, naive_design_{index})",
        f"result_{index} <- survey_rows(",
        '  c("domain estimation (correct)", "filter then analyze (naive)"),',
        f"  c(as.numeric(coef(domain_{index})), as.numeric(coef(naive_{index}))),",
        f"  c(as.numeric(SE(domain_{index})), as.numeric(SE(naive_{index}))),",
        f"  rep(nrow(inside_{index}), 2),",
        f"  rep(sum(inside_{index}$w_), 2),",
        f"  rep(mean(inside_{index}$y_), 2),",
        f'  dof_{index}, "weighted_mean"',
        ")",
        f'names(result_{index})[1] <- "approach"',
        "# The naive interval uses the FILTERED design's degrees of freedom, which is",
        "# part of what makes it wrong; survey_rows above used the full design's for",
        "# both rows, so the naive interval is recomputed here.",
        f"naive_margin_{index} <- qt({_TAIL}, degf(naive_design_{index}))"
        f" * as.numeric(SE(naive_{index}))",
        f"result_{index}$ci95_low[2] <- as.numeric(coef(naive_{index})) - naive_margin_{index}",
        f"result_{index}$ci95_high[2] <- as.numeric(coef(naive_{index})) + naive_margin_{index}",
        f"stats_{index} <- list(",
        f"  n = nrow(inside_{index}),",
        f"  n_out_of_domain = nrow(sd_{index}) - nrow(inside_{index}),",
        f"  weighted_mean = as.numeric(coef(domain_{index})),",
        f"  unweighted_mean = mean(inside_{index}$y_),",
        f"  sum_of_weights = sum(inside_{index}$w_),",
        f"  standard_error = as.numeric(SE(domain_{index})),",
        f"  ci95_low = result_{index}$ci95_low[1],",
        f"  ci95_high = result_{index}$ci95_high[1],",
        f"  degrees_of_freedom = dof_{index},",
        f"  naive_standard_error = as.numeric(SE(naive_{index})),",
        f"  naive_degrees_of_freedom = degf(naive_design_{index}),",
        f"  standard_error_ratio = as.numeric(SE(naive_{index})) / as.numeric(SE(domain_{index})),",
        f"  effect_size = (weighted.mean(inside_{index}$y_, inside_{index}$w_)",
        f"    - mean(inside_{index}$y_)) / sd(inside_{index}$y_)",
        ")",
        f"show_result({r_literal(label)}, result_{index}, stats_{index})",
    ]
