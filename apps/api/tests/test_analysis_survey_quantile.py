"""Tier 6 weighted quantiles — the estimate, and Woodruff's interval around it.

Every expected number is ground truth worked out away from the implementation:
the quantile itself from the weighted CDF by hand, the interval from the
linearized variance of an indicator written out term by term, and identities
that must hold whatever the code does (equal weights reproduce the unweighted
quantile; rescaling every weight cannot move a design-based statistic).

This matters more for a median than for a mean. A weighted mean at least moves
visibly when the weights change; a weighted median can sit on the same observed
value for a wide range of weights, so an implementation that quietly ignored the
weights would return a number that looks entirely reasonable.

Convention under test: the inverse-CDF ("lower") quantile. With the weighted
CDF F(x) = sum_i w_i [y_i <= x] / sum_i w_i, the p-th quantile is the smallest
observed value whose F is at least p. It always returns a value that is in the
data, and it is the definition Woodruff's interval inverts.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.services.analysis_executor import ExecutionError, execute_spec


def _run(df, params, label="T"):
    spec = {"operations": [{"op": "weighted_quantile", "label": label, "params": params}]}
    return execute_spec(df, spec)[0]


def _rows(result) -> list[dict]:
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


@pytest.fixture
def hand_frame() -> pd.DataFrame:
    """Six rows with weights 1,1,1,3,3,3 — the CDF is computable in one line.

        y = 10 20 30 40 50 60      w = 1 1 1 3 3 3

    sum(w) = 12 and the cumulative weights are 1, 2, 3, 6, 9, 12, so

        F = 1/12, 2/12, 3/12, 6/12, 9/12, 12/12
          = .0833  .1667  .25   .50   .75   1.0

    The median is the first y whose F reaches .5, which is 40. The unweighted
    median of the same six values is 30 — the weights move it by one step.
    """
    return pd.DataFrame(
        {
            "spend": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "weight": [1.0, 1.0, 1.0, 3.0, 3.0, 3.0],
            "region": ["north", "north", "north", "south", "south", "south"],
        }
    )


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


# The Woodruff interval for the hand frame's median, worked out by hand.
#
# At the estimate Q = 40 the indicator u = [y <= 40] is [1,1,1,1,0,0] and its
# weighted mean is (1+1+1+3)/12 = .5. Linearized, the contributions are
# c_i = w_i (u_i - .5) / 12 = [1/24, 1/24, 1/24, 1/8, -1/8, -1/8], which sum to
# zero, so with no strata and no clusters
#
#     V = (6/5) * sum c^2 = (6/5) * (3/576 + 3/64) = .0625   ->   SE = .25
#
# On 5 degrees of freedom the half-width in probability is t * .25, which is
# larger than .5, so both endpoints clip to the ends of the CDF: the interval
# runs from the smallest observed value to the largest.
HAND_F_SE = 0.25
HAND_DOF = 5
HAND_T = float(stats.t.ppf(0.975, HAND_DOF))
HAND_CI = (10.0, 60.0)
HAND_QUANTILE_SE = (HAND_CI[1] - HAND_CI[0]) / (2 * HAND_T)


class TestTheEstimateItself:
    def test_weighted_median_is_the_inverse_cdf_of_the_weighted_distribution(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        assert result.stats["weighted_quantile"] == pytest.approx(40.0)

    def test_the_unweighted_median_is_reported_beside_it(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        assert result.stats["unweighted_quantile"] == pytest.approx(30.0)

    def test_the_two_differ_so_the_weights_demonstrably_did_something(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        assert result.stats["weighted_quantile"] != result.stats["unweighted_quantile"]

    @pytest.mark.parametrize(("p", "expected"), [(0.25, 30.0), (0.5, 40.0), (0.75, 50.0)])
    def test_other_quantiles_read_off_the_same_cdf(self, hand_frame, p, expected):
        result = _run(hand_frame, {"column": "spend", "weights": "weight", "quantile": p})
        assert result.stats["weighted_quantile"] == pytest.approx(expected)

    def test_the_quantile_is_always_a_value_from_the_data(self, hand_frame):
        for p in (0.1, 0.33, 0.5, 0.66, 0.9):
            result = _run(hand_frame, {"column": "spend", "weights": "weight", "quantile": p})
            assert result.stats["weighted_quantile"] in set(hand_frame["spend"])

    def test_the_quantile_never_decreases_as_p_rises(self, hand_frame):
        values = [
            _run(hand_frame, {"column": "spend", "weights": "weight", "quantile": p}).stats[
                "weighted_quantile"
            ]
            for p in (0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9)
        ]
        assert values == sorted(values)


class TestIdentitiesThatMustHold:
    def test_equal_weights_reproduce_the_unweighted_quantile(self, equal_frame):
        result = _run(equal_frame, {"column": "score", "weights": "weight"})
        expected = float(np.quantile(equal_frame["score"], 0.5, method="inverted_cdf"))
        assert result.stats["weighted_quantile"] == pytest.approx(expected)
        assert result.stats["unweighted_quantile"] == pytest.approx(expected)

    def test_rescaling_every_weight_changes_nothing(self, hand_frame):
        """A design-based statistic cannot depend on the scale of the weights."""
        scaled = hand_frame.assign(weight=hand_frame["weight"] * 37.5)
        base = _run(hand_frame, {"column": "spend", "weights": "weight"}).stats
        rescaled = _run(scaled, {"column": "spend", "weights": "weight"}).stats
        assert rescaled["weighted_quantile"] == pytest.approx(base["weighted_quantile"])
        assert rescaled["standard_error"] == pytest.approx(base["standard_error"])

    def test_the_median_ignores_an_extreme_value_that_drags_the_mean(self):
        """The reason to ask for a median at all."""
        frame = pd.DataFrame(
            {
                "income": [30_000.0, 32_000.0, 34_000.0, 36_000.0, 9_000_000.0],
                "weight": [1.0, 1.0, 1.0, 1.0, 1.0],
            }
        )
        median = _run(frame, {"column": "income", "weights": "weight"}).stats
        assert median["weighted_quantile"] == pytest.approx(34_000.0)
        assert float(frame["income"].mean()) > 1_000_000.0


class TestWoodruffInterval:
    def test_the_standard_error_matches_the_hand_computation(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        assert result.stats["standard_error"] == pytest.approx(HAND_QUANTILE_SE)

    def test_the_interval_matches_the_hand_computation(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        interval = result.stats["confidence_interval"]
        assert (interval["low"], interval["high"]) == pytest.approx(HAND_CI)

    def test_the_interval_brackets_the_estimate(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        interval = result.stats["confidence_interval"]
        assert interval["low"] <= result.stats["weighted_quantile"] <= interval["high"]

    def test_a_larger_sample_gives_a_tighter_interval(self):
        """Woodruff inverts the CDF interval, so more data must narrow it."""
        rng = np.random.default_rng(20260909)

        def width(n: int) -> float:
            frame = pd.DataFrame({"y": rng.normal(100.0, 15.0, n), "w": rng.gamma(9.0, 1 / 9.0, n)})
            stats_ = _run(frame, {"column": "y", "weights": "w"}).stats
            interval = stats_["confidence_interval"]
            return interval["high"] - interval["low"]

        assert width(2000) < width(80)

    def test_the_degrees_of_freedom_are_the_design_ones(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        assert result.stats["degrees_of_freedom"] == pytest.approx(HAND_DOF)


class TestGrouping:
    def test_each_group_is_estimated_as_its_own_domain(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight", "group_by": ["region"]})
        rows = _rows(result)
        assert {row["region"] for row in rows} == {"north", "south"}

    def test_a_group_quantile_comes_from_that_group_alone(self, hand_frame):
        """North is 10,20,30 at weight 1 — its median is 20 whatever south does."""
        result = _run(hand_frame, {"column": "spend", "weights": "weight", "group_by": ["region"]})
        north = next(row for row in _rows(result) if row["region"] == "north")
        assert north["weighted_quantile"] == pytest.approx(20.0)


class TestRefusals:
    def test_a_quantile_of_zero_or_one_is_rejected(self, hand_frame):
        from app.services.analysis_registry import ColumnRoles
        from app.services.analysis_spec import validate_spec

        roles = ColumnRoles.from_dataframe(hand_frame)
        for p in (0.0, 1.0):
            issues = validate_spec(
                {
                    "operations": [
                        {
                            "op": "weighted_quantile",
                            "label": "T",
                            "params": {"column": "spend", "weights": "weight", "quantile": p},
                        }
                    ]
                },
                roles,
            )
            assert issues, f"quantile={p} should not validate"

    def test_a_sensible_quantile_validates(self, hand_frame):
        from app.services.analysis_registry import ColumnRoles
        from app.services.analysis_spec import validate_spec

        roles = ColumnRoles.from_dataframe(hand_frame)
        assert (
            validate_spec(
                {
                    "operations": [
                        {
                            "op": "weighted_quantile",
                            "label": "T",
                            "params": {"column": "spend", "weights": "weight", "quantile": 0.9},
                        }
                    ]
                },
                roles,
            )
            == []
        )

    def test_a_column_with_no_positive_weights_is_refused(self):
        frame = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0], "w": [0.0, 0.0, 0.0, 0.0]})
        with pytest.raises(ExecutionError):
            _run(frame, {"column": "y", "weights": "w"})

    def test_too_few_rows_to_estimate_a_variance_is_refused(self):
        frame = pd.DataFrame({"y": [1.0], "w": [1.0]})
        with pytest.raises(ExecutionError):
            _run(frame, {"column": "y", "weights": "w"})


class TestReportedContext:
    def test_the_payload_names_the_quantile_it_estimated(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight", "quantile": 0.25})
        assert result.stats["quantile"] == pytest.approx(0.25)
        assert "0.25" in result.stats["estimate"] or "25" in result.stats["estimate"]

    def test_the_design_is_described(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        assert "design" in result.stats
        assert result.stats["sum_of_weights"] == pytest.approx(12.0)

    def test_the_method_is_named_so_a_reader_can_check_it(self, hand_frame):
        result = _run(hand_frame, {"column": "spend", "weights": "weight"})
        text = " ".join(result.notes).lower()
        assert "woodruff" in text

    def test_strata_and_clusters_are_honoured(self):
        """Declaring the design must change the interval, or it was ignored."""
        rng = np.random.default_rng(7)
        n = 120
        frame = pd.DataFrame(
            {
                "y": rng.normal(50.0, 10.0, n),
                "w": rng.gamma(9.0, 1 / 9.0, n),
                "stratum": np.repeat(["s1", "s2", "s3", "s4"], n // 4),
                "psu": np.repeat([f"p{i}" for i in range(12)], n // 12),
            }
        )
        plain = _run(frame, {"column": "y", "weights": "w"}).stats
        designed = _run(
            frame, {"column": "y", "weights": "w", "strata": "stratum", "cluster": "psu"}
        ).stats
        assert designed["degrees_of_freedom"] != plain["degrees_of_freedom"]
        assert math.isfinite(designed["standard_error"])
