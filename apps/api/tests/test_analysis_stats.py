"""Effect sizes, intervals, and assumption checks under degenerate input.

The happy paths are covered by the operations that use these helpers. What is
pinned here is what happens when the data cannot support the statistic: zero
variance, a single observation, an empty group, a proportion of exactly 0 or 1.

Every one of these must return None rather than NaN. NaN is not valid JSON, and
a statistic that silently becomes 0.0 is worse than one that is absent — the
narrator can say "could not be computed", but it cannot un-report a number.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from app.services.analysis_stats import (
    ALPHA,
    check_equal_variance,
    check_expected_counts,
    check_group_sizes,
    check_normality,
    check_paired_completeness,
    cohens_d_independent,
    cohens_d_one_sample,
    cohens_h,
    cohens_w,
    cramers_v,
    effect_size,
    eta_squared,
    eta_squared_rank,
    interval,
    json_safe,
    magnitude,
    mean_ci,
    mean_difference_ci,
    omega_squared,
    proportion_difference_ci,
    rank_biserial_mann_whitney,
    rank_biserial_wilcoxon,
    welch_dof,
    wilson_ci,
)


def _is_nan(value: float) -> bool:
    return isinstance(value, float) and math.isnan(value)


class TestJsonSafe:
    def test_non_finite_becomes_none(self):
        assert json_safe(float("nan")) is None
        assert json_safe(float("inf")) is None
        assert json_safe(float("-inf")) is None

    def test_non_numeric_becomes_none(self):
        assert json_safe("not a number") is None
        assert json_safe(None) is None

    def test_ordinary_values_round_to_decimals(self):
        assert json_safe(1 / 3) == 0.333333
        assert json_safe(2.5, places=1) == 2.5

    def test_tiny_values_keep_significant_figures(self):
        # Decimal rounding would make both of these 0.0, which for a p-value
        # claims certainty no test can support.
        assert json_safe(8.370431e-07) == pytest.approx(8.37043e-07, rel=1e-9)
        assert json_safe(3.14e-30) == pytest.approx(3.14e-30, rel=1e-9)

    def test_exact_zero_stays_zero(self):
        assert json_safe(0.0) == 0.0

    def test_numpy_scalars_survive(self):
        assert json_safe(np.float64(0.5)) == 0.5
        assert json_safe(np.int64(3)) == 3.0


class TestMagnitude:
    @pytest.mark.parametrize(
        "value,expected",
        [(0.1, "negligible"), (0.3, "small"), (0.6, "medium"), (1.2, "large"), (-1.2, "large")],
    )
    def test_cohen_d_bands(self, value, expected):
        assert magnitude(value, "cohen_d") == expected

    @pytest.mark.parametrize(
        "value,expected",
        [(0.005, "negligible"), (0.03, "small"), (0.10, "medium"), (0.30, "large")],
    )
    def test_variance_explained_bands(self, value, expected):
        assert magnitude(value, "variance_explained") == expected

    def test_uncomputable_effects_have_no_label(self):
        assert magnitude(None, "cohen_d") is None
        assert magnitude(float("nan"), "correlation") is None

    def test_effect_size_payload_is_json_safe(self):
        payload = effect_size("Cohen's d", float("nan"), "cohen_d", hedges_g=float("nan"))
        assert payload["value"] is None
        assert payload["magnitude"] is None
        assert payload["hedges_g"] is None
        assert "convention" in payload["benchmark"]
        json.dumps(payload, allow_nan=False)


class TestEffectSizesRefuseDegenerateInput:
    def test_cohens_d_needs_two_observations_per_group(self):
        d, g = cohens_d_independent([1.0], [2.0, 3.0])
        assert _is_nan(d) and _is_nan(g)

    def test_cohens_d_needs_variance(self):
        d, g = cohens_d_independent([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
        assert _is_nan(d) and _is_nan(g)

    def test_hedges_g_shrinks_d_at_small_n(self):
        d, g = cohens_d_independent([1.0, 2, 3], [4.0, 5, 6])
        # g = d * (1 - 3/(4*6-9)) = d * 12/15
        assert g == pytest.approx(d * 12 / 15, abs=1e-9)
        assert abs(g) < abs(d)

    def test_one_sample_d_needs_variance(self):
        assert _is_nan(cohens_d_one_sample([4.0, 4.0, 4.0], 2.0))

    def test_cohens_h_rejects_values_outside_zero_to_one(self):
        assert _is_nan(cohens_h(1.4, 0.5))
        assert _is_nan(cohens_h(0.5, -0.1))

    def test_cohens_h_is_zero_for_equal_proportions(self):
        assert cohens_h(0.4, 0.4) == pytest.approx(0.0, abs=1e-12)

    def test_cramers_v_needs_a_two_dimensional_table(self):
        assert _is_nan(cramers_v(10.0, 100, 1, 3))
        assert _is_nan(cramers_v(10.0, 0, 2, 2))
        assert _is_nan(cramers_v(float("nan"), 100, 2, 2))

    def test_cohens_w_needs_observations(self):
        assert _is_nan(cohens_w(10.0, 0))

    def test_eta_squared_needs_total_variance(self):
        assert _is_nan(eta_squared(0.0, 0.0))

    def test_omega_squared_can_go_negative_for_a_null_effect(self):
        # Less biased than eta squared, and the bias correction can overshoot.
        assert omega_squared(1.0, 100.0, 3, 10.0) < 0

    def test_rank_eta_squared_needs_more_rows_than_groups(self):
        assert _is_nan(eta_squared_rank(5.0, 3, 3))
        assert _is_nan(eta_squared_rank(float("nan"), 3, 30))

    def test_rank_biserial_needs_both_groups(self):
        assert _is_nan(rank_biserial_mann_whitney(0.0, 0, 5))

    def test_wilcoxon_rank_biserial_needs_a_nonzero_difference(self):
        assert _is_nan(rank_biserial_wilcoxon([0.0, 0.0, 0.0]))
        assert _is_nan(rank_biserial_wilcoxon([]))

    def test_wilcoxon_rank_biserial_is_signed_by_the_balance_of_ranks(self):
        assert rank_biserial_wilcoxon([1.0, 2.0, 3.0]) == pytest.approx(1.0)
        assert rank_biserial_wilcoxon([-1.0, -2.0, -3.0]) == pytest.approx(-1.0)


class TestIntervals:
    def test_mean_ci_needs_two_observations(self):
        low, high = mean_ci([5.0])
        assert _is_nan(low) and _is_nan(high)

    def test_mean_ci_of_a_constant_is_a_point(self):
        assert mean_ci([7.0, 7.0, 7.0]) == (7.0, 7.0)

    def test_pooled_interval_differs_from_welch(self):
        a, b = [1.0, 2, 3, 4, 5], [10.0, 20, 30, 40, 50]
        pooled = mean_difference_ci(a, b, equal_var=True)
        welch = mean_difference_ci(a, b, equal_var=False)
        assert pooled != welch
        # Both bracket the same point estimate.
        assert sum(pooled) / 2 == pytest.approx(sum(welch) / 2, abs=1e-9)

    def test_difference_interval_needs_two_per_group(self):
        low, high = mean_difference_ci([1.0], [2.0, 3.0], equal_var=False)
        assert _is_nan(low) and _is_nan(high)

    def test_difference_interval_of_two_constants_is_uncomputable(self):
        low, high = mean_difference_ci([2.0, 2.0], [5.0, 5.0], equal_var=False)
        assert _is_nan(low) and _is_nan(high)

    def test_welch_dof_needs_two_per_group(self):
        assert _is_nan(welch_dof(1.0, 1, 1.0, 5))
        assert _is_nan(welch_dof(0.0, 5, 0.0, 5))

    def test_wilson_interval_stays_inside_zero_and_one(self):
        # The normal approximation runs past the boundary here; Wilson does not.
        low, high = wilson_ci(0, 10)
        assert low == 0.0 and 0 < high < 1
        low, high = wilson_ci(10, 10)
        # Exactly 1.0 up to floating-point noise in the centre/margin arithmetic.
        assert high == pytest.approx(1.0, abs=1e-12)
        assert 0 < low < 1

    def test_wilson_interval_needs_observations(self):
        low, high = wilson_ci(0, 0)
        assert _is_nan(low) and _is_nan(high)

    def test_proportion_difference_interval_stays_in_range(self):
        low, high = proportion_difference_ci(0, 20, 20, 20)
        assert -1.0 <= low < high <= 1.0

    def test_proportion_difference_needs_both_groups(self):
        low, high = proportion_difference_ci(1, 0, 2, 10)
        assert _is_nan(low) and _is_nan(high)

    def test_interval_payload_is_json_safe(self):
        payload = interval(float("nan"), float("inf"), of="the difference")
        assert payload["low"] is None and payload["high"] is None
        assert payload["level"] == 0.95
        json.dumps(payload, allow_nan=False)


class TestAssumptionChecks:
    def test_normality_is_not_testable_below_three_observations(self):
        check = check_normality([1.0, 2.0], label="x")
        assert check.passed is None
        assert "not testable" in check.detail

    def test_normality_is_not_testable_without_variance(self):
        check = check_normality([3.0] * 10, label="x")
        assert check.passed is None
        assert "no variance" in check.detail

    def test_large_samples_use_dagostino_instead_of_shapiro(self):
        # Shapiro-Wilk's p-value is unreliable above 5,000 observations.
        rng = np.random.default_rng(7)
        check = check_normality(rng.normal(size=6000), label="x")
        assert "D'Agostino" in check.detail

    def test_a_departure_from_normality_is_tolerated_at_large_n(self):
        # The central limit theorem covers the mean; saying otherwise would
        # have the narrator raise an alarm the data do not justify.
        rng = np.random.default_rng(11)
        check = check_normality(rng.exponential(size=400), label="income")
        assert check.passed is False
        assert "robust" in check.detail

    def test_a_departure_at_small_n_recommends_a_rank_test(self):
        check = check_normality([1.0, 1, 1, 1, 1, 1, 1, 50], label="x")
        assert check.passed is False
        assert "rank-based" in check.detail

    def test_equal_variance_needs_two_usable_groups(self):
        check = check_equal_variance([[1.0, 2.0], [3.0]], labels=["a", "b"])
        assert check.passed is None

    def test_equal_variance_is_not_testable_without_variance(self):
        check = check_equal_variance([[2.0, 2.0], [5.0, 5.0]], labels=["a", "b"])
        assert check.passed is None
        assert "zero variance" in check.detail

    def test_unequal_spreads_fail_and_are_quantified(self):
        rng = np.random.default_rng(3)
        check = check_equal_variance(
            [rng.normal(0, 1, 80), rng.normal(0, 12, 80)], labels=["tight", "wide"]
        )
        assert check.passed is False
        assert "sd =" in check.detail

    def test_group_sizes_flag_the_smallest_group(self):
        check = check_group_sizes({"a": 40, "b": 3})
        assert check.passed is False
        assert "'b'" in check.detail and "n = 3" in check.detail

    def test_group_sizes_with_no_groups(self):
        assert check_group_sizes({}).passed is None

    def test_expected_counts_report_how_many_cells_are_thin(self):
        check = check_expected_counts(np.array([[10.0, 2.0], [1.0, 30.0]]))
        assert check.passed is False
        assert "2 of 4 cells" in check.detail

    def test_expected_counts_with_no_cells(self):
        assert check_expected_counts(np.array([])).passed is None

    def test_complete_pairs_passes_when_nothing_was_dropped(self):
        assert check_paired_completeness(50, 0).passed is True

    def test_assumption_serializes_with_non_finite_statistics(self):
        check = check_normality([1.0, 2.0], label="x")
        payload = check.to_dict()
        assert payload["passed"] is None
        json.dumps(payload, allow_nan=False)

    def test_alpha_is_the_conventional_threshold(self):
        assert ALPHA == 0.05


class TestEqualVarianceLabelsMatchTheGroupsTested:
    """Levene drops groups with one observation; the printed spreads must too.

    ``usable`` filters those groups out but ``labels`` was not filtered, so the
    zipped detail string attached each surviving group's sd to the *previous*
    group's name and never showed the last one. Both current callers run
    ``require_group_sizes`` first, so this was a trap rather than a live bug —
    the next caller that does not would print confidently wrong spreads.
    """

    def test_each_spread_is_attributed_to_its_own_group(self):
        singleton = [1.0]
        wide = [1.0, 2.0, 3.0, 4.0, 50.0]  # sd = 21.272047
        narrow = [2.0, 2.0, 2.0, 2.0, 2.5]  # sd = 0.223607
        check = check_equal_variance(
            [singleton, wide, narrow], labels=["A(n=1)", "B", "C"]
        )
        assert "B sd = 21.27" in check.detail
        assert "C sd = 0.2236" in check.detail
        assert "A(n=1) sd" not in check.detail

    def test_the_untested_group_is_named(self):
        check = check_equal_variance(
            [[1.0], [1.0, 2.0, 3.0], [4.0, 5.0, 9.0]], labels=["A", "B", "C"]
        )
        assert "A" in check.detail
        assert "1 group(s)" in check.detail

    def test_no_dropped_groups_reads_as_before(self):
        check = check_equal_variance([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], labels=["A", "B"])
        assert "A sd = 1" in check.detail
        assert "B sd = 1" in check.detail
        assert "not in this test" not in check.detail
