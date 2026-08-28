"""Tier 6 survey estimation — weighted estimates, design effects, Rao-Scott.

Every expected number here is ground truth computed away from the
implementation: hand arithmetic written out term by term, a closed form
(Kish's DEFF is exactly 1 + CV squared), an identity that must hold (equal
weights reproduce the unweighted estimate exactly; scaling every weight by a
constant cannot move a design-based statistic), or scipy computing the same
quantity by a different route.

That matters more here than anywhere else in the pipeline. A weighted mean
that is quietly wrong looks exactly like a weighted mean that is right — there
is no plausibility check a reader can apply to "the weighted mean is 42.5" —
so a test that only asserted "a number came back" would pass against an
implementation that had silently dropped the weights.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.services.analysis_executor import ExecutionError, execute_spec
from app.services.analysis_registry import ColumnRoles
from app.services.analysis_spec import validate_spec
from app.services.analysis_survey import SURVEY_OPERATION_DEFS, SURVEY_OPERATIONS


def _run(df, op, params, label="T"):
    return execute_spec(df, {"operations": [{"op": op, "label": label, "params": params}]})[0]


def _rows(result) -> list[dict]:
    """Result rows as dicts, so a test names a column instead of an index."""
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


def _row(result, key: str, value: str) -> dict:
    for row in _rows(result):
        if str(row[key]) == value:
            return row
    raise AssertionError(f"no row with {key}={value!r}; have {_rows(result)}")


def _assumption(result, needle: str) -> dict:
    for check in result.stats.get("assumptions", []):
        if needle.lower() in check["name"].lower():
            return check
    raise AssertionError(
        f"no assumption matching {needle!r}; have "
        f"{[c['name'] for c in result.stats.get('assumptions', [])]}"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hand_frame() -> pd.DataFrame:
    """Six rows with weights 1,1,1,3,3,3 — every statistic hand-computable.

        y = 10 20 30 40 50 60      w = 1 1 1 3 3 3

    sum(w) = 12, sum(w*y) = 60 + 450 = 510, so the weighted mean is 510/12 =
    42.5 against an unweighted mean of 210/6 = 35.

    Variance of the weighted mean, by Taylor linearization with no strata and
    no clusters, is (n/(n-1)) * sum(w^2 (y - 42.5)^2) / (sum w)^2.  The six
    terms of that sum are

        1*1056.25  1*506.25  1*156.25  9*6.25  9*56.25  9*306.25
      =   1056.25    506.25    156.25   56.25   506.25   2756.25  -> 5037.5

    so V = (6/5) * 5037.5 / 144 = 41.979166..., SE = 6.4791331...
    """
    return pd.DataFrame(
        {
            "spend": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "weight": [1.0, 1.0, 1.0, 3.0, 3.0, 3.0],
            "region": ["north", "north", "north", "south", "south", "south"],
        }
    )


HAND_VARIANCE = (6 / 5) * 5037.5 / 144
HAND_SE = math.sqrt(HAND_VARIANCE)

# w*y = 10, 20, 30, 120, 150, 180; mean 85; deviations -75 -65 -55 35 65 95;
# squares 5625 4225 3025 1225 4225 9025 -> 27350;  V = (6/5)*27350 = 32820.
HAND_TOTAL_VARIANCE = (6 / 5) * 27350.0


@pytest.fixture
def equal_frame() -> pd.DataFrame:
    """Five rows carrying the same weight — the weights must cancel out."""
    return pd.DataFrame(
        {
            "score": [3.0, 7.0, 11.0, 19.0, 23.0],
            "weight": [4.0, 4.0, 4.0, 4.0, 4.0],
            "arm": ["a", "a", "b", "b", "b"],
        }
    )


@pytest.fixture
def survey_frame() -> pd.DataFrame:
    """A 120-respondent survey with unequal weights and two design columns."""
    rng = np.random.default_rng(20260827)
    n = 120
    return pd.DataFrame(
        {
            "income": rng.normal(50_000, 12_000, n).round(2),
            "weight": rng.gamma(4.0, 25.0, n).round(4),
            "gender": rng.choice(["female", "male"], n),
            "region": rng.choice(["north", "south", "east"], n),
            "stratum": np.repeat(["s1", "s2", "s3", "s4"], n // 4),
            "psu": np.repeat([f"p{i}" for i in range(12)], n // 12),
        }
    )


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_every_declared_operation_has_a_handler(self):
        assert set(SURVEY_OPERATION_DEFS) == set(SURVEY_OPERATIONS)

    def test_every_operation_is_tier_six(self):
        assert {d.tier for d in SURVEY_OPERATION_DEFS.values()} == {6}

    def test_handlers_are_reachable_through_the_executor(self, hand_frame):
        from app.services.analysis_executor import _DISPATCH

        for name in SURVEY_OPERATION_DEFS:
            assert _DISPATCH[name] is SURVEY_OPERATIONS[name]

    def test_summaries_state_what_the_design_support_is(self):
        """The planner must not be told this tier can do something it cannot."""
        joined = " ".join(
            f"{d.summary} {d.requires}" for d in SURVEY_OPERATION_DEFS.values()
        ).lower()
        assert "replicate" in joined


# ---------------------------------------------------------------------------
# Equal weights: the weights must cancel exactly
# ---------------------------------------------------------------------------


class TestEqualWeights:
    def test_weighted_mean_equals_the_unweighted_mean(self, equal_frame):
        result = _run(equal_frame, "weighted_mean", {"column": "score", "weights": "weight"})
        values = equal_frame["score"].to_numpy()

        assert result.stats["weighted_mean"] == pytest.approx(values.mean())
        assert result.stats["unweighted_mean"] == pytest.approx(values.mean())

    def test_standard_error_equals_the_ordinary_standard_error(self, equal_frame):
        result = _run(equal_frame, "weighted_mean", {"column": "score", "weights": "weight"})
        values = equal_frame["score"].to_numpy()
        expected = values.std(ddof=1) / math.sqrt(values.size)

        assert result.stats["standard_error"] == pytest.approx(expected)

    def test_confidence_interval_is_the_ordinary_t_interval(self, equal_frame):
        result = _run(equal_frame, "weighted_mean", {"column": "score", "weights": "weight"})
        values = equal_frame["score"].to_numpy()
        margin = stats.t.ppf(0.975, 4) * values.std(ddof=1) / math.sqrt(5)

        interval = result.stats["confidence_interval"]
        assert interval["low"] == pytest.approx(values.mean() - margin)
        assert interval["high"] == pytest.approx(values.mean() + margin)

    def test_design_effect_is_exactly_one(self, equal_frame):
        result = _run(equal_frame, "design_effect", {"column": "score", "weights": "weight"})

        assert result.stats["design_effect_kish"] == pytest.approx(1.0)
        assert result.stats["design_effect_design_based"] == pytest.approx(1.0)
        assert result.stats["effective_sample_size"] == pytest.approx(5.0)
        assert result.stats["weight_cv"] == pytest.approx(0.0)

    def test_weighted_total_equals_the_scaled_sum(self, equal_frame):
        result = _run(equal_frame, "weighted_total", {"column": "score", "weights": "weight"})

        assert result.stats["weighted_total"] == pytest.approx(4 * equal_frame["score"].sum())
        assert result.stats["unweighted_sum"] == pytest.approx(equal_frame["score"].sum())


# ---------------------------------------------------------------------------
# Hand-computed arithmetic
# ---------------------------------------------------------------------------


class TestHandComputed:
    def test_weighted_mean_and_sum_of_weights(self, hand_frame):
        result = _run(hand_frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert result.stats["weighted_mean"] == pytest.approx(42.5)
        assert result.stats["unweighted_mean"] == pytest.approx(35.0)
        assert result.stats["sum_of_weights"] == pytest.approx(12.0)
        assert result.n == 6

    def test_standard_error_matches_the_hand_computed_variance(self, hand_frame):
        result = _run(hand_frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert result.stats["standard_error"] == pytest.approx(HAND_SE)
        assert result.stats["standard_error"] == pytest.approx(6.4791331724, abs=1e-6)

    def test_confidence_interval_uses_n_minus_one_degrees_of_freedom(self, hand_frame):
        result = _run(hand_frame, "weighted_mean", {"column": "spend", "weights": "weight"})
        margin = stats.t.ppf(0.975, 5) * HAND_SE

        assert result.stats["degrees_of_freedom"] == pytest.approx(5)
        assert "n - 1" in result.stats["degrees_of_freedom_basis"]
        assert result.stats["confidence_interval"]["low"] == pytest.approx(42.5 - margin)
        assert result.stats["confidence_interval"]["high"] == pytest.approx(42.5 + margin)

    def test_weighted_total_and_its_standard_error(self, hand_frame):
        result = _run(hand_frame, "weighted_total", {"column": "spend", "weights": "weight"})

        assert result.stats["weighted_total"] == pytest.approx(510.0)
        assert result.stats["standard_error"] == pytest.approx(math.sqrt(HAND_TOTAL_VARIANCE))

    def test_kish_design_effect_matches_one_plus_cv_squared(self, hand_frame):
        """w = 1,1,1,3,3,3 has mean 2 and population sd 1, so CV = 0.5."""
        result = _run(hand_frame, "design_effect", {"column": "spend", "weights": "weight"})

        assert result.stats["weight_cv"] == pytest.approx(0.5)
        assert result.stats["design_effect_kish"] == pytest.approx(1 + 0.5**2)
        assert result.stats["design_effect_kish"] == pytest.approx(1.25)
        assert result.stats["effective_sample_size"] == pytest.approx(6 / 1.25)
        assert result.stats["effective_sample_size"] == pytest.approx(4.8)

    def test_design_effect_reads_plainly(self, hand_frame):
        result = _run(hand_frame, "design_effect", {"column": "spend", "weights": "weight"})

        assert "6" in result.stats["reading"]
        assert "4.8" in result.stats["reading"]


class TestExpandedFrame:
    """An integer weight of w must behave like w copies of the row."""

    def test_weighted_total_matches_the_expanded_frame(self):
        frame = pd.DataFrame(
            {"units": [2.0, 5.0, 11.0], "weight": [4.0, 1.0, 3.0], "grp": ["a", "a", "b"]}
        )
        expanded = frame.loc[frame.index.repeat(frame["weight"].astype(int))]

        result = _run(frame, "weighted_total", {"column": "units", "weights": "weight"})

        assert expanded.shape[0] == 8
        assert result.stats["weighted_total"] == pytest.approx(expanded["units"].sum())
        assert result.stats["weighted_total"] == pytest.approx(2 * 4 + 5 + 11 * 3)

    def test_weighted_mean_matches_the_expanded_frame_mean(self):
        frame = pd.DataFrame({"units": [2.0, 5.0, 11.0], "weight": [4.0, 1.0, 3.0]})
        expanded = frame.loc[frame.index.repeat(frame["weight"].astype(int))]

        result = _run(frame, "weighted_mean", {"column": "units", "weights": "weight"})

        assert result.stats["weighted_mean"] == pytest.approx(expanded["units"].mean())

    def test_weight_sum_is_reported_as_the_estimated_population(self):
        frame = pd.DataFrame({"units": [2.0, 5.0, 11.0], "weight": [4.0, 1.0, 3.0]})
        result = _run(frame, "weighted_total", {"column": "units", "weights": "weight"})

        assert result.stats["sum_of_weights"] == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Grouped estimation
# ---------------------------------------------------------------------------


class TestGroupBy:
    def test_group_estimates_are_hand_computable(self, hand_frame):
        result = _run(
            hand_frame,
            "weighted_mean",
            {"column": "spend", "weights": "weight", "group_by": ["region"]},
        )

        north = _row(result, "region", "north")
        south = _row(result, "region", "south")
        assert north["weighted_mean"] == pytest.approx(20.0)
        assert north["unweighted_mean"] == pytest.approx(20.0)
        assert south["weighted_mean"] == pytest.approx(50.0)
        assert south["sum_of_weights"] == pytest.approx(9.0)

    def test_every_group_reports_both_figures(self, survey_frame):
        result = _run(
            survey_frame,
            "weighted_mean",
            {"column": "income", "weights": "weight", "group_by": ["region"]},
        )

        assert "weighted_mean" in result.columns
        assert "unweighted_mean" in result.columns
        for row in _rows(result):
            assert row["weighted_mean"] is not None
            assert row["unweighted_mean"] is not None
            unweighted = survey_frame.loc[survey_frame["region"] == row["region"], "income"].mean()
            assert row["unweighted_mean"] == pytest.approx(unweighted, rel=1e-9)

    def test_the_estimate_is_the_second_column_so_charts_plot_it(self, survey_frame):
        """The executor's fallback charts column 1; it must not be a sample size."""
        result = _run(
            survey_frame,
            "weighted_mean",
            {"column": "income", "weights": "weight", "group_by": ["region"]},
        )
        assert result.columns[1] == "weighted_mean"


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------


class TestWeightValidation:
    def test_negative_weights_are_refused_by_count(self, hand_frame):
        frame = hand_frame.assign(weight=[1.0, -2.0, 1.0, -0.5, 3.0, 3.0])

        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        message = str(excinfo.value)
        assert "2" in message
        assert "negative" in message.lower()

    def test_all_zero_weights_are_refused(self, hand_frame):
        frame = hand_frame.assign(weight=0.0)

        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert "no positive" in str(excinfo.value).lower()

    def test_all_missing_weights_are_refused(self, hand_frame):
        frame = hand_frame.assign(weight=[None] * 6)

        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert "weight" in str(excinfo.value).lower()

    def test_zero_weight_rows_are_dropped_and_counted(self, hand_frame):
        frame = hand_frame.assign(weight=[1.0, 0.0, 1.0, 3.0, 3.0, 0.0])

        result = _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert result.n == 4
        assert result.n_excluded == 2
        assert any("2 row" in note and "zero weight" in note for note in result.notes)

    def test_missing_values_are_dropped_listwise_and_explained(self, hand_frame):
        frame = hand_frame.assign(
            spend=[10.0, None, 30.0, 40.0, 50.0, 60.0],
            weight=[1.0, 1.0, None, 3.0, 3.0, 3.0],
        )

        result = _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert result.n == 4
        assert result.n_excluded == 2
        joined = " ".join(result.notes)
        assert "2 row" in joined
        assert "bias" in joined.lower()

    def test_missing_weights_are_flagged_as_a_possible_bias(self, hand_frame):
        frame = hand_frame.assign(weight=[1.0, 1.0, None, 3.0, 3.0, 3.0])

        result = _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})
        check = _assumption(result, "weight completeness")

        assert check["passed"] is None
        assert "1" in check["detail"]

    def test_extreme_weight_variation_is_flagged_with_its_numbers(self):
        frame = pd.DataFrame(
            {
                "spend": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                "weight": [1.0, 1.0, 1.0, 1.0, 1.0, 400.0],
            }
        )

        result = _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})
        check = _assumption(result, "weight variation")

        assert check["passed"] is False
        assert "400" in check["detail"]

    def test_moderate_weight_variation_passes(self, hand_frame):
        result = _run(hand_frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert _assumption(result, "weight variation")["passed"] is True

    def test_too_few_rows_to_estimate_a_variance_is_refused(self):
        frame = pd.DataFrame({"spend": [10.0], "weight": [2.0]})

        with pytest.raises(ExecutionError) as excinfo:
            _run(frame, "weighted_mean", {"column": "spend", "weights": "weight"})

        assert "1" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Small domains
# ---------------------------------------------------------------------------


class TestSmallSamples:
    def test_a_three_person_domain_is_flagged_by_its_count(self, survey_frame):
        frame = pd.concat(
            [
                survey_frame,
                pd.DataFrame(
                    {
                        "income": [10_000.0, 12_000.0, 14_000.0],
                        "weight": [80.0, 90.0, 100.0],
                        "gender": ["female"] * 3,
                        "region": ["west"] * 3,
                        "stratum": ["s1"] * 3,
                        "psu": ["p0"] * 3,
                    }
                ),
            ],
            ignore_index=True,
        )

        result = _run(
            frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "region",
                "subpopulation_value": "west",
            },
        )
        check = _assumption(result, "sample size")

        assert check["passed"] is False
        assert "3" in check["detail"]
        assert "30" in check["detail"]
        assert any("3 respondent" in note for note in result.notes)

    def test_a_small_group_is_flagged_in_a_grouped_estimate(self, hand_frame):
        result = _run(
            hand_frame,
            "weighted_mean",
            {"column": "spend", "weights": "weight", "group_by": ["region"]},
        )
        check = _assumption(result, "sample size")

        assert check["passed"] is False
        assert "3" in check["detail"]

    def test_a_single_row_domain_is_refused(self, survey_frame):
        frame = pd.concat(
            [
                survey_frame,
                pd.DataFrame(
                    {
                        "income": [10_000.0],
                        "weight": [80.0],
                        "gender": ["female"],
                        "region": ["west"],
                        "stratum": ["s1"],
                        "psu": ["p0"],
                    }
                ),
            ],
            ignore_index=True,
        )

        with pytest.raises(ExecutionError) as excinfo:
            _run(
                frame,
                "subpopulation_estimate",
                {
                    "column": "income",
                    "weights": "weight",
                    "subpopulation": "region",
                    "subpopulation_value": "west",
                },
            )

        assert "1" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Rao-Scott
# ---------------------------------------------------------------------------


@pytest.fixture
def table_frame() -> pd.DataFrame:
    """A 2x3 table with enough cases per cell for the asymptotics to hold."""
    rng = np.random.default_rng(7)
    n = 200
    gender = rng.choice(["female", "male"], n)
    answer = np.where(
        rng.random(n) < np.where(gender == "female", 0.65, 0.35),
        "agree",
        np.where(rng.random(n) < 0.5, "neutral", "disagree"),
    )
    return pd.DataFrame(
        {
            "gender": gender,
            "answer": answer,
            "weight": rng.gamma(3.0, 40.0, n).round(4),
            "flat": np.full(n, 6.0),
        }
    )


def _observed(frame: pd.DataFrame) -> np.ndarray:
    return pd.crosstab(frame["gender"], frame["answer"]).to_numpy()


class TestRaoScott:
    def test_equal_weights_reproduce_the_ordinary_chi_square(self, table_frame):
        result = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "flat"},
        )
        ordinary = stats.chi2_contingency(_observed(table_frame), correction=False)

        assert result.stats["correction_factor"] == pytest.approx(1.0)
        assert result.stats["statistic"] == pytest.approx(float(ordinary.statistic))
        assert result.stats["uncorrected_statistic"] == pytest.approx(float(ordinary.statistic))
        assert result.stats["p_value"] == pytest.approx(float(ordinary.pvalue), abs=1e-6)

    def test_the_naive_statistic_is_inflated_by_the_weight_scale(self, table_frame):
        """With flat weights of 6, the naive statistic is exactly 6x too large."""
        result = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "flat"},
        )

        assert result.stats["naive_weighted_statistic"] == pytest.approx(
            6 * result.stats["uncorrected_statistic"]
        )

    def test_unequal_weights_give_a_correction_below_the_naive_statistic(self, table_frame):
        result = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "weight"},
        )

        assert result.stats["statistic"] < result.stats["naive_weighted_statistic"]
        assert result.stats["naive_weighted_p_value"] < result.stats["p_value"]

    def test_the_uncorrected_statistic_is_pearson_on_the_scaled_table(self, table_frame):
        """X^2 must be computed at the real sample size, not the sum of weights."""
        result = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "weight"},
        )
        weighted = pd.crosstab(
            table_frame["gender"],
            table_frame["answer"],
            values=table_frame["weight"],
            aggfunc="sum",
        ).to_numpy()
        scaled = weighted * len(table_frame) / weighted.sum()
        expected = stats.chi2_contingency(scaled, correction=False)

        assert result.stats["uncorrected_statistic"] == pytest.approx(float(expected.statistic))
        assert result.stats["statistic"] == pytest.approx(
            result.stats["uncorrected_statistic"] / result.stats["correction_factor"]
        )

    def test_the_correction_is_invariant_to_the_weight_scale(self, table_frame):
        """Multiplying every weight by a constant does not change the design."""
        scaled = table_frame.assign(weight=table_frame["weight"] * 13.0)

        base = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "weight"},
        )
        moved = _run(
            scaled, "weighted_crosstab", {"row": "gender", "column": "answer", "weights": "weight"}
        )

        assert moved.stats["correction_factor"] == pytest.approx(base.stats["correction_factor"])
        assert moved.stats["statistic"] == pytest.approx(base.stats["statistic"])
        assert moved.stats["naive_weighted_statistic"] == pytest.approx(
            13 * base.stats["naive_weighted_statistic"]
        )

    def test_it_reports_the_effective_sample_size_beside_the_statistic(self, table_frame):
        result = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "weight"},
        )

        assert result.stats["n_unweighted"] == 200
        assert result.stats["effective_sample_size"] == pytest.approx(
            200 / result.stats["correction_factor"]
        )
        assert result.stats["correction_type"].lower().startswith("first-order")

    def test_cells_carry_weighted_counts_and_percentages(self, table_frame):
        result = _run(
            table_frame,
            "weighted_crosstab",
            {"row": "gender", "column": "answer", "weights": "weight"},
        )
        cells = result.stats["cells"]
        female_agree = next(c for c in cells if c["row"] == "female" and c["column"] == "agree")
        mask = (table_frame["gender"] == "female") & (table_frame["answer"] == "agree")

        assert female_agree["unweighted_count"] == int(mask.sum())
        assert female_agree["weighted_count"] == pytest.approx(
            table_frame.loc[mask, "weight"].sum()
        )
        rows = [c for c in cells if c["row"] == "female"]
        assert sum(c["row_percent"] for c in rows) == pytest.approx(100.0)

    def test_a_degenerate_table_is_refused(self, table_frame):
        frame = table_frame.assign(answer="agree")

        with pytest.raises(ExecutionError) as excinfo:
            _run(
                frame,
                "weighted_crosstab",
                {"row": "gender", "column": "answer", "weights": "weight"},
            )

        assert "two categories" in str(excinfo.value)

    def test_no_p_value_serialises_as_zero(self):
        """A p of 1e-30 rounded to 0.0 would claim a certainty no test supports."""
        frame = pd.DataFrame(
            {
                "gender": ["female"] * 200 + ["male"] * 200,
                "answer": ["agree"] * 190 + ["disagree"] * 10 + ["agree"] * 10 + ["disagree"] * 190,
                "weight": ([2.0] * 100 + [5.0] * 100) * 2,
            }
        )

        result = _run(
            frame, "weighted_crosstab", {"row": "gender", "column": "answer", "weights": "weight"}
        )

        assert result.stats["p_value"] != 0.0
        assert 0.0 < result.stats["p_value"] < 1e-10
        assert json.loads(json.dumps(result.stats))["p_value"] != 0.0


# ---------------------------------------------------------------------------
# Subpopulation estimation
# ---------------------------------------------------------------------------


class TestSubpopulation:
    def test_the_point_estimate_equals_the_filtered_weighted_mean(self, survey_frame):
        result = _run(
            survey_frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "gender",
                "subpopulation_value": "female",
            },
        )
        inside = survey_frame[survey_frame["gender"] == "female"]
        expected = np.average(inside["income"], weights=inside["weight"])

        assert result.stats["weighted_mean"] == pytest.approx(expected)
        assert result.stats["unweighted_mean"] == pytest.approx(inside["income"].mean())

    def test_both_standard_errors_are_reported_and_they_differ(self, survey_frame):
        result = _run(
            survey_frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "gender",
                "subpopulation_value": "female",
            },
        )
        domain = result.stats["domain_estimation"]["standard_error"]
        naive = result.stats["naive_filter_then_analyze"]["standard_error"]

        assert domain != naive
        assert domain > 0 and naive > 0

    def test_the_naive_route_matches_running_the_operation_on_filtered_rows(self, survey_frame):
        """The naive figure must be exactly what filter-then-analyze produces."""
        inside = survey_frame[survey_frame["gender"] == "female"].reset_index(drop=True)
        filtered = _run(inside, "weighted_mean", {"column": "income", "weights": "weight"})

        result = _run(
            survey_frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "gender",
                "subpopulation_value": "female",
            },
        )

        assert result.stats["naive_filter_then_analyze"]["standard_error"] == pytest.approx(
            filtered.stats["standard_error"]
        )

    def test_the_domain_variance_uses_the_full_sample_degrees_of_freedom(self, survey_frame):
        result = _run(
            survey_frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "gender",
                "subpopulation_value": "female",
            },
        )
        n_domain = int((survey_frame["gender"] == "female").sum())

        assert result.stats["domain_estimation"]["degrees_of_freedom"] == pytest.approx(119)
        assert result.stats["naive_filter_then_analyze"]["degrees_of_freedom"] == pytest.approx(
            n_domain - 1
        )
        assert result.n == n_domain

    def test_the_table_shows_both_routes(self, survey_frame):
        result = _run(
            survey_frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "gender",
                "subpopulation_value": "female",
            },
        )

        approaches = [row[result.columns[0]] for row in _rows(result)]
        assert len(approaches) == 2
        assert any("domain" in str(a).lower() for a in approaches)
        assert any("filter" in str(a).lower() for a in approaches)

    def test_the_difference_between_the_routes_is_explained(self, survey_frame):
        result = _run(
            survey_frame,
            "subpopulation_estimate",
            {
                "column": "income",
                "weights": "weight",
                "subpopulation": "gender",
                "subpopulation_value": "female",
            },
        )

        joined = " ".join(result.notes).lower()
        assert "filter" in joined
        assert "variance" in joined

    def test_an_absent_subpopulation_value_is_refused(self, survey_frame):
        with pytest.raises(ExecutionError) as excinfo:
            _run(
                survey_frame,
                "subpopulation_estimate",
                {
                    "column": "income",
                    "weights": "weight",
                    "subpopulation": "gender",
                    "subpopulation_value": "nonbinary",
                },
            )

        assert "nonbinary" in str(excinfo.value)

    def test_the_validator_rejects_an_unknown_subpopulation_value(self, survey_frame):
        roles = ColumnRoles.from_dataframe(survey_frame)
        problems = validate_spec(
            {
                "operations": [
                    {
                        "op": "subpopulation_estimate",
                        "label": "T",
                        "params": {
                            "column": "income",
                            "weights": "weight",
                            "subpopulation": "gender",
                            "subpopulation_value": "Female",
                        },
                    }
                ]
            },
            roles,
        )

        assert problems
        assert any("Female" in problem and "female" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Design: strata, clusters, fpc
# ---------------------------------------------------------------------------


class TestDesign:
    def test_clustering_uses_psu_minus_strata_degrees_of_freedom(self, survey_frame):
        result = _run(
            survey_frame,
            "weighted_mean",
            {
                "column": "income",
                "weights": "weight",
                "strata": "stratum",
                "cluster": "psu",
            },
        )

        assert result.stats["degrees_of_freedom"] == pytest.approx(12 - 4)
        assert "PSU" in result.stats["degrees_of_freedom_basis"]
        assert result.stats["design"]["n_psu"] == 12
        assert result.stats["design"]["n_strata"] == 4

    def test_clustering_changes_the_standard_error(self, survey_frame):
        plain = _run(survey_frame, "weighted_mean", {"column": "income", "weights": "weight"})
        clustered = _run(
            survey_frame,
            "weighted_mean",
            {"column": "income", "weights": "weight", "strata": "stratum", "cluster": "psu"},
        )

        assert clustered.stats["standard_error"] != pytest.approx(
            plain.stats["standard_error"], rel=1e-6
        )

    def test_the_point_estimate_is_unchanged_by_the_design(self, survey_frame):
        plain = _run(survey_frame, "weighted_mean", {"column": "income", "weights": "weight"})
        clustered = _run(
            survey_frame,
            "weighted_mean",
            {"column": "income", "weights": "weight", "strata": "stratum", "cluster": "psu"},
        )

        assert clustered.stats["weighted_mean"] == pytest.approx(plain.stats["weighted_mean"])

    def test_a_finite_population_correction_shrinks_the_variance(self, hand_frame):
        plain = _run(hand_frame, "weighted_mean", {"column": "spend", "weights": "weight"})
        corrected = _run(
            hand_frame, "weighted_mean", {"column": "spend", "weights": "weight", "fpc": 0.75}
        )

        assert corrected.stats["standard_error"] == pytest.approx(
            plain.stats["standard_error"] * math.sqrt(0.25)
        )

    def test_a_singleton_stratum_is_refused_by_name(self, survey_frame):
        frame = survey_frame.copy()
        frame.loc[frame.index[0], "stratum"] = "lonely"
        frame.loc[frame.index[0], "psu"] = "lonely_psu"

        with pytest.raises(ExecutionError) as excinfo:
            _run(
                frame,
                "weighted_mean",
                {
                    "column": "income",
                    "weights": "weight",
                    "strata": "stratum",
                    "cluster": "psu",
                },
            )

        message = str(excinfo.value)
        assert "lonely" in message
        assert "1" in message

    def test_the_declared_design_is_stated_as_an_assumption(self, survey_frame):
        result = _run(survey_frame, "weighted_mean", {"column": "income", "weights": "weight"})
        check = _assumption(result, "design")

        assert check["passed"] is None
        assert "cluster" in check["detail"].lower()

    def test_the_design_based_effect_reflects_clustering(self, survey_frame):
        plain = _run(survey_frame, "design_effect", {"column": "income", "weights": "weight"})
        clustered = _run(
            survey_frame,
            "design_effect",
            {"column": "income", "weights": "weight", "strata": "stratum", "cluster": "psu"},
        )

        assert plain.stats["design_effect_kish"] == pytest.approx(
            clustered.stats["design_effect_kish"]
        )
        assert clustered.stats["design_effect_design_based"] != pytest.approx(
            plain.stats["design_effect_design_based"], rel=1e-6
        )


# ---------------------------------------------------------------------------
# The output contract
# ---------------------------------------------------------------------------


ALL_OPERATIONS = [
    ("weighted_mean", {"column": "income", "weights": "weight"}),
    ("weighted_total", {"column": "income", "weights": "weight"}),
    ("weighted_crosstab", {"row": "gender", "column": "region", "weights": "weight"}),
    ("design_effect", {"column": "income", "weights": "weight"}),
    (
        "subpopulation_estimate",
        {
            "column": "income",
            "weights": "weight",
            "subpopulation": "gender",
            "subpopulation_value": "female",
        },
    ),
]


class TestOutputContract:
    @pytest.mark.parametrize(("op", "params"), ALL_OPERATIONS)
    def test_every_operation_reports_assumptions(self, survey_frame, op, params):
        result = _run(survey_frame, op, params)

        assert result.stats["assumptions"]
        for check in result.stats["assumptions"]:
            assert set(check) == {"name", "passed", "detail", "statistic", "p_value"}

    @pytest.mark.parametrize(("op", "params"), ALL_OPERATIONS)
    def test_every_operation_reports_an_effect_size(self, survey_frame, op, params):
        result = _run(survey_frame, op, params)

        assert result.stats["effect_size"]["name"]
        assert result.stats["effect_size"]["magnitude"]

    @pytest.mark.parametrize(("op", "params"), ALL_OPERATIONS)
    def test_every_operation_reports_the_design_it_assumed(self, survey_frame, op, params):
        result = _run(survey_frame, op, params)

        assert result.stats["design"]["weights"] == "weight"
        assert "linearization" in result.stats["design"]["variance_estimator"].lower()

    @pytest.mark.parametrize(("op", "params"), ALL_OPERATIONS)
    def test_every_operation_serialises(self, survey_frame, op, params):
        result = _run(survey_frame, op, params)

        json.dumps({"stats": result.stats, "table": result.to_table(), "notes": result.notes})

    @pytest.mark.parametrize(
        ("op", "params"),
        [entry for entry in ALL_OPERATIONS if entry[0] != "weighted_crosstab"],
    )
    def test_every_estimate_reports_both_weighted_and_unweighted(self, survey_frame, op, params):
        result = _run(survey_frame, op, params)

        assert (
            result.stats.get("weighted_mean") is not None
            or result.stats.get("weighted_total") is not None
        )
        assert (
            result.stats.get("unweighted_mean") is not None
            or result.stats.get("unweighted_sum") is not None
        )
