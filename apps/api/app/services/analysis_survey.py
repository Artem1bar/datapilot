"""Tier 6: survey estimation — the operations that respect a sampling design.

An unweighted mean computed on a weighted survey is not an approximation of the
right answer, it is a different quantity: it describes the people who happened
to respond rather than the population they were sampled to represent. Every
other tier in this pipeline is free to ignore that. This one exists because
survey exports are what this product is pointed at — the cleaning pipeline
already recognizes Qualtrics-shaped files — and because the estimation half of
that recognition was never built.

Declares its operations in ``SURVEY_OPERATION_DEFS`` and their implementations
in ``SURVEY_OPERATIONS``, keyed by the same names.
:mod:`app.services.analysis_spec` merges the first into the validated whitelist
and :mod:`app.services.analysis_executor` merges the second into the dispatch
table, so this module is the only place a tier-6 operation is defined. The
arithmetic lives next door in :mod:`app.services.analysis_survey_variance`,
where each formula is written above the function that implements it.

Design support — what is honoured, and what is refused
------------------------------------------------------

A full design-based analysis needs four things: weights, strata, primary
sampling units, and a finite population correction. This pass supports:

* **Weights** — always, and required. Every operation here takes a ``weights``
  column and no operation here falls back to an unweighted estimate.
* **Strata** (``strata``) and **clusters** (``cluster``) — supported, via
  Taylor linearization with the ultimate-cluster variance estimator, the
  standard approach and the default in R's ``survey`` and Stata's ``svy``.
  Degrees of freedom follow the design: PSUs minus strata, which is n - 1 when
  neither is declared. Every result states which it used.
* **Finite population correction** (``fpc``) — supported as a single sampling
  fraction applied to every stratum.

Deliberately refused, rather than approximated under a design-aware name:

* **Replicate weights** (BRR, jackknife, bootstrap, JK2). A file of 80
  replicate weight columns is a different variance estimator, not a parameter
  of this one, and pretending otherwise would return a linearization variance
  under a replication label.
* **Per-stratum population sizes.** ``fpc`` is one fraction for the whole
  design; a survey with different sampling fractions by stratum needs a column
  of population sizes, which this pass does not read.
* **Stages below the first.** The ultimate-cluster estimator treats PSUs as
  sampled with replacement, which is the usual convention: it is exact when the
  first-stage fraction is negligible and conservative otherwise.
* **The estimation of the weights themselves.** Post-stratification, raking and
  calibration all make the weights random, and a design that accounted for that
  would have slightly different (usually smaller) standard errors. The weights
  are taken as fixed, and the results say so.
* **Single-PSU strata.** Refused by name rather than assigned an arbitrary
  variance contribution.

The narrator is told all of this through each operation's ``summary`` and
``requires`` text, so the planner cannot promise a user something the executor
will not do.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analysis_prep import assumptions, significant
from app.services.analysis_registry import ColumnRoles, OperationDef, Param
from app.services.analysis_result import ExecutionError, OperationResult, frame_to_result
from app.services.analysis_stats import (
    Assumption,
    check_expected_counts,
    cramers_v,
    effect_size,
    interval,
)
from app.services.analysis_survey_variance import (
    Estimate,
    SurveyData,
    design_effect,
    pearson_statistic,
    prepare_survey_data,
    profile_weights,
    rao_scott_factor,
    restrict,
    sample_size_check,
    small_domain_notes,
    weighted_mean,
    weighted_total,
)

# Below this, there is no estimate at all: a variance needs two observations.
MIN_ESTIMABLE_N = 2

# A weighted crosstab computes a design effect per cell and per margin, so the
# cost is linear in cells. Past this the table is unreadable anyway.
MAX_CROSSTAB_CELLS = 100


# ---------------------------------------------------------------------------
# Shared reporting
# ---------------------------------------------------------------------------


def _weighting_shift(values: np.ndarray, weights: np.ndarray) -> dict[str, Any]:
    """What the weighting changed, in standard deviations.

    The effect size this tier owes the output contract is not about a
    hypothesis: it is "how far did weighting move the answer", which is the
    question a reader has the moment they see two means side by side.
    """
    if values.size < 2:  # pragma: no cover - guarded by MIN_ESTIMABLE_N
        return effect_size("Weighting shift (Cohen's d)", math.nan, "cohen_d")
    unweighted = float(values.mean())
    weighted = float((weights * values).sum() / weights.sum())
    sd = float(values.std(ddof=1))
    shift = (weighted - unweighted) / sd if sd > 0 else math.nan
    return effect_size(
        "Weighting shift (Cohen's d)",
        shift,
        "cohen_d",
        weighted_mean=weighted,
        unweighted_mean=unweighted,
        direction="positive means weighting raised the estimate",
    )


def _domains(frame: pd.DataFrame, group_by: list[str] | None) -> list[tuple[str, np.ndarray]]:
    """Domain indicators, in sorted label order so the table is stable."""
    if not group_by:
        return [("(all respondents)", np.ones(len(frame), dtype=bool))]
    labels = frame[group_by].astype(str).agg(" / ".join, axis=1)
    return [(label, (labels == label).to_numpy()) for label in sorted(labels.unique())]


def _group_column(group_by: list[str] | None) -> str:
    return " / ".join(group_by) if group_by else "measure"


def _estimate_row(label: str, estimate: Estimate, *, value_key: str) -> dict[str, Any]:
    """One row of an estimate table, with the estimate at index 1.

    Column order is load-bearing: the executor's chart fallback plots the
    second column, so a sample size there would put group sizes under a title
    promising weighted means.
    """
    unweighted_key = "unweighted_mean" if value_key == "weighted_mean" else "unweighted_sum"
    return {
        "label": label,
        value_key: estimate.value,
        unweighted_key: estimate.unweighted,
        "n": estimate.n,
        "sum_of_weights": estimate.sum_weights,
        "standard_error": estimate.standard_error,
        "ci95_low": estimate.ci_low,
        "ci95_high": estimate.ci_high,
        "relative_se": estimate.coefficient_of_variation,
    }


def _design_payload(
    data: SurveyData, values: np.ndarray, domain: np.ndarray | None = None
) -> dict[str, Any]:
    """The keys every operation in this tier reports, whatever it computes.

    *domain* restricts the weighting-shift effect size to a subpopulation, so
    the reported shift is the one for the estimate actually being made.
    """
    weights = data.design.weights
    inside = values if domain is None else values[domain]
    inside_weights = weights if domain is None else weights[domain]
    return {
        "design": data.design.describe(),
        "degrees_of_freedom": data.design.dof,
        "degrees_of_freedom_basis": data.design.dof_basis,
        "effect_size": _weighting_shift(inside, inside_weights),
    }


def _finish(
    frame: pd.DataFrame,
    data: SurveyData,
    *,
    op: str,
    label: str,
    n: int,
    payload: dict[str, Any],
    extra_notes: list[str],
    extra_checks: tuple[Assumption, ...] = (),
) -> OperationResult:
    payload["assumptions"] = assumptions(*data.checks, *extra_checks)
    return frame_to_result(
        frame,
        op=op,
        label=label,
        n=n,
        n_excluded=data.n_excluded,
        notes=data.notes + extra_notes,
        stats_payload=payload,
    )


# ---------------------------------------------------------------------------
# weighted_mean / weighted_total
# ---------------------------------------------------------------------------


def _grouped_estimates(
    data: SurveyData, column: str, group_by: list[str] | None, *, of_total: bool
) -> tuple[pd.DataFrame, dict[str, Estimate], dict[str, int], dict[str, float]]:
    values = data.frame[column].to_numpy(dtype=float)
    estimator = weighted_total if of_total else weighted_mean
    value_key = "weighted_total" if of_total else "weighted_mean"

    estimates: dict[str, Estimate] = {}
    rows: list[dict[str, Any]] = []
    for label, indicator in _domains(data.frame, group_by):
        estimate = estimator(data.design, values, indicator)
        estimates[label] = estimate
        rows.append(_estimate_row(label, estimate, value_key=value_key))

    frame = pd.DataFrame(rows).rename(columns={"label": _group_column(group_by)})
    counts = {label: estimate.n for label, estimate in estimates.items()}
    weights = {label: estimate.sum_weights for label, estimate in estimates.items()}
    return frame, estimates, counts, weights


def _scalar_keys(estimate: Estimate, *, value_key: str, of: str) -> dict[str, Any]:
    unweighted_key = "unweighted_mean" if value_key == "weighted_mean" else "unweighted_sum"
    return {
        value_key: estimate.value,
        unweighted_key: estimate.unweighted,
        "standard_error": estimate.standard_error,
        "confidence_interval": interval(estimate.ci_low, estimate.ci_high, of=of),
        "relative_standard_error": estimate.coefficient_of_variation,
        "sum_of_weights": estimate.sum_weights,
    }


def op_weighted_mean(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """The population mean the sample was designed to estimate, with its SE."""
    column = params["column"]
    group_by = params.get("group_by")
    data = prepare_survey_data(
        df, params, numeric_columns=(column,), label_columns=tuple(group_by or ())
    )
    frame, estimates, counts, weights = _grouped_estimates(data, column, group_by, of_total=False)

    payload: dict[str, Any] = {
        "estimate": f"Weighted mean of {column}, using {params['weights']} as the design weight",
        "n": len(data.frame),
        **_design_payload(data, data.frame[column].to_numpy(dtype=float)),
    }
    if group_by:
        payload["grouped_by"] = list(group_by)
        payload["groups"] = len(estimates)
    else:
        payload.update(
            _scalar_keys(
                estimates["(all respondents)"],
                value_key="weighted_mean",
                of=f"the population mean of {column}",
            )
        )

    return _finish(
        frame,
        data,
        op="weighted_mean",
        label=label,
        n=len(data.frame),
        payload=payload,
        extra_notes=small_domain_notes(counts, weights),
        extra_checks=(sample_size_check(counts),),
    )


def op_weighted_total(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """The population total, which is only ever as good as the weights."""
    column = params["column"]
    group_by = params.get("group_by")
    data = prepare_survey_data(
        df, params, numeric_columns=(column,), label_columns=tuple(group_by or ())
    )
    frame, estimates, counts, weights = _grouped_estimates(data, column, group_by, of_total=True)

    payload: dict[str, Any] = {
        "estimate": f"Estimated population total of {column}",
        "n": len(data.frame),
        "estimated_population": data.design.sum_weights,
        **_design_payload(data, data.frame[column].to_numpy(dtype=float)),
    }
    if group_by:
        payload["grouped_by"] = list(group_by)
        payload["groups"] = len(estimates)
    else:
        payload.update(
            _scalar_keys(
                estimates["(all respondents)"],
                value_key="weighted_total",
                of=f"the population total of {column}",
            )
        )

    calibration = (
        f"This total is only as good as the weights' calibration to a population. The "
        f"weights sum to {data.design.sum_weights:,.0f}, so that is the population size "
        f"being claimed; if {params['weights']!r} was not calibrated to a real population "
        f"count, the total is on an arbitrary scale and only its relative pattern means "
        f"anything. The unweighted sum beside it is the sample's own total, not an estimate "
        f"of anything larger."
    )
    return _finish(
        frame,
        data,
        op="weighted_total",
        label=label,
        n=len(data.frame),
        payload=payload,
        extra_notes=[calibration, *small_domain_notes(counts, weights)],
        extra_checks=(sample_size_check(counts),),
    )


# ---------------------------------------------------------------------------
# design_effect
# ---------------------------------------------------------------------------


def _reading(n: int, effective: float) -> str:
    """The sentence this operation exists to produce."""
    if not math.isfinite(effective):  # pragma: no cover - guarded by _prepare
        return f"{n:,} responses; the effective sample size could not be computed"
    rendered = f"{effective:,.1f}" if effective < 100 else f"{effective:,.0f}"
    return (
        f"{n:,} responses carry the statistical weight of about {rendered} equally-weighted "
        f"ones. Precision follows the effective sample size, not the response count."
    )


def _design_effect_row(
    data: SurveyData, label: str, values: np.ndarray, indicator: np.ndarray
) -> dict[str, Any]:
    profile = profile_weights(data.design.weights[indicator])
    estimate = weighted_mean(data.design, values, indicator)
    return {
        "label": label,
        "effective_sample_size": profile.effective_n,
        "n": profile.n,
        "design_effect_kish": profile.deff,
        "design_effect_design_based": design_effect(data.design, values, indicator),
        "weight_cv": profile.cv,
        "weight_min": profile.minimum,
        "weight_max": profile.maximum,
        "sum_of_weights": profile.sum_weights,
        "weighted_mean": estimate.value,
        "unweighted_mean": estimate.unweighted,
    }


def op_design_effect(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """How much precision the weighting (and any clustering) actually cost."""
    column = params["column"]
    group_by = params.get("group_by")
    data = prepare_survey_data(
        df, params, numeric_columns=(column,), label_columns=tuple(group_by or ())
    )
    values = data.frame[column].to_numpy(dtype=float)

    rows = [
        _design_effect_row(data, domain_label, values, indicator)
        for domain_label, indicator in _domains(data.frame, group_by)
    ]
    frame = pd.DataFrame(rows).rename(columns={"label": _group_column(group_by)})

    overall = profile_weights(data.design.weights)
    based = design_effect(data.design, values)
    payload: dict[str, Any] = {
        "estimate": f"Design effect and effective sample size for {column}",
        "n": overall.n,
        "reading": _reading(overall.n, overall.effective_n),
        "design_effect_kish": overall.deff,
        "design_effect_design_based": based,
        "effective_sample_size": overall.effective_n,
        "effective_sample_size_design_based": (
            overall.n / based if math.isfinite(based) and based > 0 else math.nan
        ),
        "weight_cv": overall.cv,
        "weight_min": overall.minimum,
        "weight_max": overall.maximum,
        "sum_of_weights": overall.sum_weights,
        "weighted_mean": weighted_mean(data.design, values).value,
        "unweighted_mean": float(values.mean()),
        "interpretation": (
            "Kish's design effect comes from the weights alone and assumes the weighting is "
            "unrelated to the variable; the design-based one is the ratio of this variable's "
            "actual design variance to what simple random sampling of the same n would have "
            "given, so it also carries any clustering. They agree when the weights are "
            "unrelated to the outcome and diverge when they are not."
        ),
        **_design_payload(data, values),
    }
    if group_by:
        payload["grouped_by"] = list(group_by)

    counts = {str(row[_group_column(group_by)]): int(row["n"]) for row in frame.to_dict("records")}
    return _finish(
        frame,
        data,
        op="design_effect",
        label=label,
        n=overall.n,
        payload=payload,
        extra_notes=[],
        extra_checks=(sample_size_check(counts),),
    )


# ---------------------------------------------------------------------------
# weighted_crosstab, with the Rao-Scott correction
# ---------------------------------------------------------------------------


def _weighted_table(frame: pd.DataFrame, row: str, column: str, weights: str) -> pd.DataFrame:
    table = pd.crosstab(
        frame[row].astype(str), frame[column].astype(str), values=frame[weights], aggfunc="sum"
    ).fillna(0.0)
    table = table.loc[table.sum(axis=1) > 0, table.sum(axis=0) > 0]
    if table.shape[0] < 2 or table.shape[1] < 2:
        raise ExecutionError(
            f"weighted_crosstab: needs at least two categories in each of {row!r} and "
            f"{column!r}; got a {table.shape[0]}x{table.shape[1]} table"
        )
    if table.size > MAX_CROSSTAB_CELLS:
        raise ExecutionError(
            f"weighted_crosstab: {table.shape[0]}x{table.shape[1]} is "
            f"{table.size} cells, past the limit of {MAX_CROSSTAB_CELLS}. A design-corrected "
            f"test needs a design effect per cell, and a table this size has too few "
            f"respondents per cell to support one. Collapse the categories first."
        )
    return table


def _cells(table: pd.DataFrame, unweighted: pd.DataFrame, total: float) -> list[dict[str, Any]]:
    row_totals = table.sum(axis=1)
    column_totals = table.sum(axis=0)
    return [
        {
            "row": str(row_label),
            "column": str(column_label),
            "weighted_count": float(table.loc[row_label, column_label]),
            "unweighted_count": int(unweighted.loc[row_label, column_label]),
            "row_percent": float(100 * table.loc[row_label, column_label] / row_totals[row_label]),
            "column_percent": float(
                100 * table.loc[row_label, column_label] / column_totals[column_label]
            ),
            "total_percent": float(100 * table.loc[row_label, column_label] / total),
        }
        for row_label in table.index
        for column_label in table.columns
    ]


def op_weighted_crosstab(df: pd.DataFrame, params: dict[str, Any], label: str) -> OperationResult:
    """A weighted contingency table with a design-corrected test of independence."""
    row_column, column_column = params["row"], params["column"]
    if row_column == column_column:
        raise ExecutionError("weighted_crosstab: 'row' and 'column' must be different columns")

    data = prepare_survey_data(
        df, params, numeric_columns=(), label_columns=(row_column, column_column)
    )
    frame = data.frame
    table = _weighted_table(frame, row_column, column_column, params["weights"])
    unweighted = pd.crosstab(frame[row_column].astype(str), frame[column_column].astype(str))
    unweighted = unweighted.reindex(index=table.index, columns=table.columns, fill_value=0)

    n = len(frame)
    population = float(table.to_numpy().sum())
    proportions = table.to_numpy(dtype=float) / population

    uncorrected = pearson_statistic(proportions, n)
    naive = pearson_statistic(proportions, population)
    factor = rao_scott_factor(
        data, frame[row_column].astype(str), frame[column_column].astype(str), proportions
    )
    dof = (table.shape[0] - 1) * (table.shape[1] - 1)
    corrected = uncorrected / factor if factor > 0 else math.nan
    p_value = float(stats.chi2.sf(corrected, dof)) if math.isfinite(corrected) else math.nan

    expected = np.outer(proportions.sum(axis=1), proportions.sum(axis=0)) * n
    payload: dict[str, Any] = {
        "test": (
            f"Rao-Scott corrected chi-square test of independence ({row_column} x {column_column})"
        ),
        "correction_type": "first-order Rao-Scott (mean generalized design effect)",
        "statistic": corrected,
        "dof": int(dof),
        "p_value": p_value,
        "significant_at_0.05": significant(p_value),
        "correction_factor": factor,
        "uncorrected_statistic": uncorrected,
        "naive_weighted_statistic": naive,
        "naive_weighted_p_value": float(stats.chi2.sf(naive, dof)),
        "effective_sample_size": n / factor if factor > 0 else math.nan,
        "n_unweighted": n,
        "estimated_population": population,
        "table_shape": f"{table.shape[0]}x{table.shape[1]}",
        "cells": _cells(table, unweighted, population),
        **_design_payload(data, np.zeros(n)),
        "effect_size": effect_size(
            "Cramér's V",
            cramers_v(uncorrected, n, *table.shape),
            "correlation",
            computed_from="Pearson's X² at the real sample size, not the sum of weights",
        ),
    }

    flat = table.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    notes = [
        f"Cell values are weighted counts summing to an estimated population of "
        f"{population:,.0f} from {n} respondents.",
        f"The naive chi-square on those weighted counts is "
        f"{naive:,.1f} — it treats {population:,.0f} weighted units as if they were "
        f"{population:,.0f} independent observations, which is the commonest error in "
        f"published survey analysis. The corrected statistic is {corrected:,.4g} on "
        f"{dof} degrees of freedom, after dividing by a design correction of {factor:.4g}.",
    ]
    return _finish(
        flat,
        data,
        op="weighted_crosstab",
        label=label,
        n=n,
        payload=payload,
        extra_notes=notes,
        extra_checks=(check_expected_counts(expected),),
    )


# ---------------------------------------------------------------------------
# subpopulation_estimate
# ---------------------------------------------------------------------------


def _naive_estimate(data: SurveyData, values: np.ndarray, mask: np.ndarray) -> Estimate | None:
    """What filter-then-analyze would have produced — computed by doing exactly that."""
    filtered = restrict(data.design, mask)
    try:
        filtered.validate()
        return weighted_mean(filtered, values[mask])
    except ExecutionError:
        # Filtering can destroy the design outright (a stratum left with one
        # PSU). That failure is itself the argument for domain estimation.
        return None


def op_subpopulation_estimate(
    df: pd.DataFrame, params: dict[str, Any], label: str
) -> OperationResult:
    """A domain mean, done as domain estimation rather than filter-then-analyze."""
    column = params["column"]
    subpopulation = params["subpopulation"]
    wanted = str(params["subpopulation_value"])

    data = prepare_survey_data(
        df, params, numeric_columns=(column,), label_columns=(subpopulation,)
    )
    labels = data.frame[subpopulation].astype(str)
    mask = (labels == wanted).to_numpy()
    domain_n = int(mask.sum())
    if domain_n == 0:
        raise ExecutionError(
            f"subpopulation_estimate: {subpopulation!r} has no value {wanted!r} among the "
            f"usable rows (values: {sorted(labels.unique())[:20]})"
        )
    if domain_n < MIN_ESTIMABLE_N:
        raise ExecutionError(
            f"subpopulation_estimate: only {domain_n} respondent(s) in {subpopulation} = "
            f"{wanted!r}; a standard error needs at least {MIN_ESTIMABLE_N}"
        )

    values = data.frame[column].to_numpy(dtype=float)
    domain = weighted_mean(data.design, values, mask)
    naive = _naive_estimate(data, values, mask)

    rows = [_estimate_row("domain estimation (correct)", domain, value_key="weighted_mean")]
    if naive is not None:
        rows.append(_estimate_row("filter then analyze (naive)", naive, value_key="weighted_mean"))
    frame = pd.DataFrame(rows).rename(columns={"label": "approach"})

    payload: dict[str, Any] = {
        "estimate": f"Weighted mean of {column} for {subpopulation} = {wanted!r}",
        "subpopulation": f"{subpopulation} = {wanted!r}",
        "n": domain_n,
        "n_out_of_domain": len(data.frame) - domain_n,
        "weighted_mean": domain.value,
        "unweighted_mean": domain.unweighted,
        "sum_of_weights": domain.sum_weights,
        "domain_estimation": {
            "standard_error": domain.standard_error,
            "confidence_interval": interval(
                domain.ci_low, domain.ci_high, of=f"the population mean of {column} in the domain"
            ),
            "degrees_of_freedom": domain.dof,
            "n_used_for_variance": len(data.frame),
        },
        "naive_filter_then_analyze": (
            {
                "standard_error": naive.standard_error,
                "confidence_interval": interval(naive.ci_low, naive.ci_high, of="the same mean"),
                "degrees_of_freedom": naive.dof,
                "n_used_for_variance": domain_n,
            }
            if naive is not None
            else {"standard_error": None, "note": "the filtered design has no estimable variance"}
        ),
        "standard_error_ratio": (
            naive.standard_error / domain.standard_error
            if naive is not None and domain.standard_error > 0
            else math.nan
        ),
        **_design_payload(data, values, mask),
    }

    explanation = (
        f"The two rows share a point estimate and differ in the standard error. Domain "
        f"estimation keeps all {len(data.frame)} respondents in the variance calculation and "
        f"uses a 0/1 domain indicator, so the strata, the primary sampling units and the "
        f"degrees of freedom stay those of the full design ({domain.dof:g} df). Filtering to "
        f"the {domain_n} in-domain rows first and analysing those recomputes the variance from "
        f"a smaller design ({naive.dof:g} df) — the sample size in the domain is random, not "
        f"fixed, and treating it as fixed is what makes the naive standard error wrong."
        if naive is not None
        else (
            f"Filter-then-analyze cannot even be computed here: dropping the "
            f"{len(data.frame) - domain_n} out-of-domain rows leaves a design with no "
            f"estimable variance. Domain estimation, which keeps them, gives {domain.dof:g} df."
        )
    )
    return _finish(
        frame,
        data,
        op="subpopulation_estimate",
        label=label,
        n=domain_n,
        payload=payload,
        extra_notes=[
            explanation,
            *small_domain_notes(
                {f"{subpopulation} = {wanted}": domain_n},
                {f"{subpopulation} = {wanted}": domain.sum_weights},
            ),
        ],
        extra_checks=(sample_size_check({f"{subpopulation} = {wanted}": domain_n}),),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_DESIGN_PARAMS = (
    Param("strata", "column"),
    Param("cluster", "column"),
    Param("fpc", "proportion"),
)

_DESIGN_RULES = (
    "'weights' is required and must be the survey's design weight column. 'strata' and "
    "'cluster' describe the sampling design and are honoured when given (Taylor "
    "linearization, degrees of freedom = PSUs minus strata); omit them only when the survey "
    "really was unstratified and unclustered, because omitting them understates the standard "
    "error. 'fpc' is one sampling fraction between 0 and 1 for the whole design. Replicate "
    "weights (BRR, jackknife, bootstrap) and per-stratum population sizes are not supported."
)


def _check_design_params(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    """The weight column cannot double as anything else in the same operation."""
    weights = params.get("weights")
    problems = [
        f"the weight column {weights!r} cannot also be used as {name!r}"
        for name in ("column", "row", "strata", "cluster", "subpopulation")
        if weights is not None and params.get(name) == weights
    ]
    group_by = params.get("group_by")
    if isinstance(group_by, list) and weights in group_by:
        problems.append(f"the weight column {weights!r} cannot also be a group_by column")
    return problems


def _check_weighted_crosstab(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    problems = _check_design_params(params, roles)
    if params.get("row") == params.get("column"):
        problems.append("'row' and 'column' must be different columns")
    return problems


def _check_subpopulation(params: dict[str, Any], roles: ColumnRoles) -> list[str]:
    """Catch a domain value that does not occur before it becomes an empty domain."""
    problems = _check_design_params(params, roles)
    column = params.get("subpopulation")
    wanted = params.get("subpopulation_value")
    known = roles.categories.get(str(column)) if isinstance(column, str) else None
    if known and wanted is not None and str(wanted) not in known:
        problems.append(
            f"subpopulation_value {wanted!r} does not occur in {column!r} "
            f"(values: {sorted(known)[:20]})"
        )
    return problems


SURVEY_OPERATION_DEFS: dict[str, OperationDef] = {
    "weighted_mean": OperationDef(
        6,
        "The population mean a weighted survey estimates, with a design-based standard "
        "error and confidence interval, and the unweighted mean beside it. Prefer this "
        "over describe/groupby_aggregate whenever the dataset has a weight column.",
        (
            Param("column", "numeric", required=True),
            Param("weights", "numeric", required=True),
            Param("group_by", "columns"),
            *_DESIGN_PARAMS,
        ),
        requires=_DESIGN_RULES + " Each group of a 'group_by' is estimated as a domain.",
        check=_check_design_params,
    ),
    "weighted_total": OperationDef(
        6,
        "The population total a weighted survey estimates, with a design-based standard "
        "error. Only meaningful when the weights are calibrated to a real population.",
        (
            Param("column", "numeric", required=True),
            Param("weights", "numeric", required=True),
            Param("group_by", "columns"),
            *_DESIGN_PARAMS,
        ),
        requires=_DESIGN_RULES,
        check=_check_design_params,
    ),
    "weighted_crosstab": OperationDef(
        6,
        "A weighted contingency table with row and column percentages, tested with a "
        "Rao-Scott corrected chi-square. Use instead of crosstab/chi_square on survey "
        "data: the ordinary test on weighted counts is inflated by the weights.",
        (
            Param("row", "column", required=True),
            Param("column", "column", required=True),
            Param("weights", "numeric", required=True),
            *_DESIGN_PARAMS,
        ),
        requires=_DESIGN_RULES + " First-order correction only; the table is capped at "
        f"{MAX_CROSSTAB_CELLS} cells.",
        check=_check_weighted_crosstab,
    ),
    "design_effect": OperationDef(
        6,
        "How much precision the weighting and clustering cost: Kish's design effect, the "
        "design-based one, the effective sample size, and the spread of the weights. "
        "Answers 'how much is this sample really worth'.",
        (
            Param("column", "numeric", required=True),
            Param("weights", "numeric", required=True),
            Param("group_by", "columns"),
            *_DESIGN_PARAMS,
        ),
        requires=_DESIGN_RULES,
        check=_check_design_params,
    ),
    "subpopulation_estimate": OperationDef(
        6,
        "A weighted mean for one subgroup, done as domain estimation rather than "
        "filter-then-analyze, reporting both standard errors so the difference is visible. "
        "Use this instead of a spec filter plus weighted_mean.",
        (
            Param("column", "numeric", required=True),
            Param("weights", "numeric", required=True),
            Param("subpopulation", "column", required=True),
            Param("subpopulation_value", "value", required=True),
            *_DESIGN_PARAMS,
        ),
        requires=_DESIGN_RULES + " 'subpopulation_value' is the category that defines the "
        "domain, spelled exactly as it appears in the data.",
        check=_check_subpopulation,
    ),
}

SURVEY_OPERATIONS = {
    "weighted_mean": op_weighted_mean,
    "weighted_total": op_weighted_total,
    "weighted_crosstab": op_weighted_crosstab,
    "design_effect": op_design_effect,
    "subpopulation_estimate": op_subpopulation_estimate,
}
