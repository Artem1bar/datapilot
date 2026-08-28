"""Tier 3 inferential statistics — statistic, effect size, CI, assumptions.

Every expected value here was computed by hand from the fixture, not read back
out of the implementation. Where a closed form exists (Welch's t on balanced
equal-variance groups, a 2x2 chi-square, a two-proportion z) the test pins the
exact number; where it does not, it pins an identity that must hold — z squared
equals the uncorrected chi-square, the rank eta squared follows from H — so a wrong
implementation cannot quietly agree with itself.

A test that only asserts "a p-value came back" would have passed against the
fabricating implementation this pipeline replaced.
"""

from __future__ import annotations

import math

import numpy
import pandas as pd
import pytest

from app.services.analysis_executor import ExecutionError, execute_spec


def _run(df, op, params, label="T"):
    return execute_spec(df, {"operations": [{"op": op, "label": label, "params": params}]})[0]


def _assumption(result, needle):
    """Find one assumption check by a substring of its name."""
    for check in result.stats.get("assumptions", []):
        if needle.lower() in check["name"].lower():
            return check
    raise AssertionError(
        f"no assumption matching {needle!r}; have "
        f"{[c['name'] for c in result.stats.get('assumptions', [])]}"
    )


@pytest.fixture
def two_groups() -> pd.DataFrame:
    """Balanced, equal-variance groups with hand-computable statistics.

    A: mean 14, sample sd sqrt(10)    B: mean 24, sample sd sqrt(10)
    Welch t = (14-24)/sqrt(10/5+10/5) = -5.0 exactly, on 8 df.
    """
    return pd.DataFrame(
        {
            "grp": ["A"] * 5 + ["B"] * 5,
            "score": [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0],
            "other": [8.0, 11.0, 15.0, 15.0, 20.0, 21.0, 21.0, 25.0, 25.0, 29.0],
        }
    )


@pytest.fixture
def three_groups() -> pd.DataFrame:
    """Three groups with F = 8.0 exactly on (2, 12) df.

    SSB = 40, SSW = 30, SST = 70 -> eta^2 = 4/7, omega^2 = 35/72.5.
    """
    return pd.DataFrame(
        {
            "grp": ["A"] * 5 + ["B"] * 5 + ["C"] * 5,
            "score": [1.0, 2, 3, 4, 5, 3, 4, 5, 6, 7, 5, 6, 7, 8, 9],
        }
    )


@pytest.fixture
def two_by_two() -> pd.DataFrame:
    """A 2x2 table with a closed-form chi-square.

              yes  no
        a      10   20
        b      30   10
    chi2 (uncorrected) = 70*(10*10-20*30)^2 / (30*40*40*30) = 12.152778
    chi2 (Yates-corrected, scipy's 2x2 default)                   = 10.510938
    Cramer's V = sqrt(12.152778/70) = 5/12
    """
    rows = [("a", "yes")] * 10 + [("a", "no")] * 20 + [("b", "yes")] * 30 + [("b", "no")] * 10
    return pd.DataFrame(rows, columns=["arm", "outcome"])


class TestTTestOneSample:
    def test_statistic_and_effect_size(self, two_groups):
        # Group A only: mean 14, sd sqrt(10)=3.162278, n=5, mu=10.
        # t = 4 / (3.162278/sqrt(5)) = 4/1.414214 = 2.828427; d = 4/3.162278 = 1.264911
        df = two_groups[two_groups["grp"] == "A"]
        result = _run(df, "ttest", {"kind": "one_sample", "column": "score", "mu": 10})

        assert result.stats["statistic"] == pytest.approx(2.828427, abs=1e-5)
        assert result.stats["dof"] == 4
        assert result.stats["effect_size"]["name"] == "Cohen's d"
        assert result.stats["effect_size"]["value"] == pytest.approx(1.264911, abs=1e-5)
        assert result.stats["effect_size"]["magnitude"] == "large"

    def test_confidence_interval_on_the_mean(self, two_groups):
        # t.ppf(0.975, 4) = 2.776445; se = 1.414214 -> margin 3.926529
        df = two_groups[two_groups["grp"] == "A"]
        result = _run(df, "ttest", {"kind": "one_sample", "column": "score", "mu": 10})
        ci = result.stats["confidence_interval"]
        assert ci["low"] == pytest.approx(14 - 3.926529, abs=1e-4)
        assert ci["high"] == pytest.approx(14 + 3.926529, abs=1e-4)
        assert ci["level"] == 0.95

    def test_mu_is_required(self, two_groups):
        with pytest.raises(ExecutionError):
            _run(two_groups, "ttest", {"kind": "one_sample", "column": "score"})


class TestTTestIndependent:
    def test_welch_statistic_is_exact(self, two_groups):
        result = _run(
            two_groups, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"}
        )
        assert result.stats["statistic"] == pytest.approx(-5.0, abs=1e-9)
        assert result.stats["dof"] == pytest.approx(8.0, abs=1e-9)
        assert result.stats["p_value"] < 0.01
        assert result.stats["significant_at_0.05"] is True

    def test_effect_size_and_difference_interval(self, two_groups):
        # pooled sd = sqrt(10) -> d = -10/3.162278 = -3.162278
        # Hedges g = d * (1 - 3/(4*10-9)) = d * 28/31 = -2.856251
        # CI on the difference: 2.306004 (t crit, 8 df) * 2.0 se = 4.612008
        result = _run(
            two_groups, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"}
        )
        effect = result.stats["effect_size"]
        assert effect["value"] == pytest.approx(-3.162278, abs=1e-5)
        assert effect["hedges_g"] == pytest.approx(-2.856251, abs=1e-5)

        ci = result.stats["confidence_interval"]
        assert ci["low"] == pytest.approx(-14.612008, abs=1e-4)
        assert ci["high"] == pytest.approx(-5.387992, abs=1e-4)

    def test_per_group_summary_is_returned(self, two_groups):
        result = _run(
            two_groups, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"}
        )
        assert result.columns[:3] == ["grp", "n", "mean"]
        means = {row[0]: row[2] for row in result.rows}
        assert means == {"A": 14.0, "B": 24.0}

    def test_levene_assumption_is_checked(self, two_groups):
        result = _run(
            two_groups, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"}
        )
        check = _assumption(result, "equal variance")
        assert check["passed"] is True  # identical variances

    def test_three_groups_is_refused_with_a_usable_message(self, three_groups):
        with pytest.raises(ExecutionError) as excinfo:
            _run(
                three_groups,
                "ttest",
                {"kind": "independent", "column": "score", "group_by": "grp"},
            )
        assert "anova" in str(excinfo.value).lower()


class TestTTestPaired:
    def test_paired_differences(self, two_groups):
        # A rows only: score-other = [2,1,-1,1,-2]; mean 0.2, sd sqrt(2.7)=1.643168
        # t = 0.2/(1.643168/sqrt(5)) = 0.272166
        df = two_groups[two_groups["grp"] == "A"]
        result = _run(df, "ttest", {"kind": "paired", "column": "score", "column2": "other"})
        assert result.stats["statistic"] == pytest.approx(0.272166, abs=1e-5)
        assert result.stats["p_value"] > 0.05
        assert result.stats["significant_at_0.05"] is False
        assert result.stats["mean_difference"] == pytest.approx(0.2, abs=1e-9)


class TestAnova:
    def test_f_statistic_is_exact(self, three_groups):
        result = _run(three_groups, "anova", {"group_by": "grp", "column": "score"})
        assert result.stats["statistic"] == pytest.approx(8.0, abs=1e-9)
        assert result.stats["df_between"] == 2
        assert result.stats["df_within"] == 12
        assert result.stats["p_value"] < 0.01

    def test_effect_sizes(self, three_groups):
        # eta^2 = SSB/SST = 40/70; omega^2 = (40 - 2*2.5)/(70+2.5)
        result = _run(three_groups, "anova", {"group_by": "grp", "column": "score"})
        effect = result.stats["effect_size"]
        assert effect["value"] == pytest.approx(40 / 70, abs=1e-6)
        assert effect["omega_squared"] == pytest.approx(35 / 72.5, abs=1e-6)

    def test_post_hoc_pairwise_comparisons(self, three_groups):
        result = _run(three_groups, "anova", {"group_by": "grp", "column": "score"})
        pairs = {(p["group_a"], p["group_b"]): p for p in result.stats["post_hoc"]["pairs"]}
        assert len(pairs) == 3
        assert pairs[("A", "C")]["difference"] == pytest.approx(-4.0, abs=1e-9)
        assert "Tukey" in result.stats["post_hoc"]["test"]

    def test_assumptions_are_reported(self, three_groups):
        result = _run(three_groups, "anova", {"group_by": "grp", "column": "score"})
        assert _assumption(result, "equal variance")["passed"] is True
        _assumption(result, "normality")
        _assumption(result, "group size")


class TestKruskal:
    def test_rank_eta_squared_follows_from_h(self, three_groups):
        result = _run(three_groups, "kruskal", {"group_by": "grp", "column": "score"})
        h = result.stats["statistic"]
        # eta^2 (rank-based) = (H - k + 1) / (n - k) with k=3, n=15. The name
        # used to say "epsilon squared", which is H / (n - 1) — a different
        # number; the code was right and the label was wrong.
        assert result.stats["effect_size"]["name"] == "eta squared (rank-based)"
        assert result.stats["effect_size"]["value"] == pytest.approx((h - 2) / 12, abs=1e-6)

    def test_reports_medians_not_means(self, three_groups):
        result = _run(three_groups, "kruskal", {"group_by": "grp", "column": "score"})
        assert "median" in result.columns
        medians = {row[0]: row[result.columns.index("median")] for row in result.rows}
        assert medians == {"A": 3.0, "B": 5.0, "C": 7.0}


class TestMannWhitney:
    def test_perfect_separation_gives_extreme_effect(self, two_groups):
        # Every A below every B -> U1 = 0 -> rank-biserial = 2*0/25 - 1 = -1
        result = _run(two_groups, "mannwhitney", {"group_by": "grp", "column": "score"})
        assert result.stats["effect_size"]["value"] == pytest.approx(-1.0, abs=1e-9)
        assert result.stats["p_value"] < 0.05

    def test_median_difference_is_reported(self, two_groups):
        result = _run(two_groups, "mannwhitney", {"group_by": "grp", "column": "score"})
        assert result.stats["median_difference"] == pytest.approx(14.0 - 24.0, abs=1e-9)


class TestWilcoxon:
    def test_all_differences_one_sign(self):
        df = pd.DataFrame({"before": [10.0, 12, 14, 16, 18], "after": [8.0, 9, 11, 15, 13]})
        # differences all positive -> W = 0, rank-biserial = 1.0
        result = _run(df, "wilcoxon", {"column": "before", "column2": "after"})
        assert result.stats["statistic"] == pytest.approx(0.0, abs=1e-9)
        assert result.stats["effect_size"]["value"] == pytest.approx(1.0, abs=1e-9)
        assert result.stats["n_pairs"] == 5


class TestChiSquare:
    def test_independence_statistic_and_effect_size(self, two_by_two):
        result = _run(
            two_by_two, "chi_square", {"kind": "independence", "row": "arm", "column": "outcome"}
        )
        # 2x2 gets Yates' correction from scipy by default.
        assert result.stats["statistic"] == pytest.approx(10.510938, abs=1e-5)
        assert result.stats["dof"] == 1
        assert result.stats["continuity_correction"] is True
        # Cramer's V is computed from the UNcorrected statistic, by convention.
        assert result.stats["effect_size"]["name"] == "Cramér's V"
        assert result.stats["effect_size"]["value"] == pytest.approx(5 / 12, abs=1e-6)

    def test_fisher_exact_is_added_for_two_by_two(self, two_by_two):
        result = _run(
            two_by_two, "chi_square", {"kind": "independence", "row": "arm", "column": "outcome"}
        )
        fisher = result.stats["fisher_exact"]
        # Categories sort to (no, yes) and (a, b), so the table is [[20,10],[10,30]]
        # and the odds ratio is (20*30)/(10*10) = 6 — the odds of "no" rather than
        # "yes", in arm a relative to arm b.
        assert fisher["odds_ratio"] == pytest.approx(6.0, abs=1e-6)
        # An odds ratio without its orientation is as likely to be read upside
        # down as the right way up, so the orientation ships with the number.
        assert "'no'" in fisher["orientation"] and "'a'" in fisher["orientation"]

    def test_expected_count_assumption(self, two_by_two):
        result = _run(
            two_by_two, "chi_square", {"kind": "independence", "row": "arm", "column": "outcome"}
        )
        check = _assumption(result, "expected")
        assert check["passed"] is True  # smallest expected cell is 12.86

    def test_small_expected_counts_fail_the_assumption(self):
        rows = [("a", "yes")] * 8 + [("a", "no")] * 1 + [("b", "yes")] * 1 + [("b", "no")] * 2
        df = pd.DataFrame(rows, columns=["arm", "outcome"])
        result = _run(df, "chi_square", {"kind": "independence", "row": "arm", "column": "outcome"})
        assert _assumption(result, "expected")["passed"] is False

    def test_goodness_of_fit_against_uniform(self):
        df = pd.DataFrame({"face": ["a"] * 30 + ["b"] * 30 + ["c"] * 30})
        result = _run(df, "chi_square", {"kind": "goodness_of_fit", "column": "face"})
        # Perfectly uniform -> chi2 = 0
        assert result.stats["statistic"] == pytest.approx(0.0, abs=1e-9)
        assert result.stats["dof"] == 2
        assert result.stats["effect_size"]["name"] == "Cohen's w"
        assert any("uniform" in note.lower() for note in result.notes)


class TestProportionTest:
    def test_two_sample_z_squared_equals_uncorrected_chi_square(self, two_by_two):
        # 10/30 vs 30/40. z = -5/12 / sqrt((4/7)(3/7)(1/30+1/40)) = -3.4860834,
        # and z^2 = 12.152778, exactly the uncorrected 2x2 chi-square.
        result = _run(
            two_by_two,
            "proportion_test",
            {"column": "outcome", "success_value": "yes", "group_by": "arm"},
        )
        z = result.stats["statistic"]
        assert z == pytest.approx(-3.4860834, abs=1e-6)
        assert z**2 == pytest.approx(12.152778, abs=1e-4)
        assert result.stats["p_value"] == pytest.approx(0.00049, abs=1e-5)

    def test_wilson_intervals_on_each_proportion(self, two_by_two):
        # Wilson 95% CI for 10/30 = (0.192308, 0.512198)
        result = _run(
            two_by_two,
            "proportion_test",
            {"column": "outcome", "success_value": "yes", "group_by": "arm"},
        )
        low = result.columns.index("ci95_low")
        high = result.columns.index("ci95_high")
        arm_a = next(row for row in result.rows if row[0] == "a")
        assert arm_a[low] == pytest.approx(0.192308, abs=1e-5)
        assert arm_a[high] == pytest.approx(0.512198, abs=1e-5)

    def test_cohens_h_effect_size(self, two_by_two):
        # h = 2*asin(sqrt(1/3)) - 2*asin(sqrt(0.75)) = -0.863445
        result = _run(
            two_by_two,
            "proportion_test",
            {"column": "outcome", "success_value": "yes", "group_by": "arm"},
        )
        assert result.stats["effect_size"]["name"] == "Cohen's h"
        assert result.stats["effect_size"]["value"] == pytest.approx(-0.863445, abs=1e-5)

    def test_one_sample_against_p0(self, two_by_two):
        # 40 successes of 70 = 0.571429 against p0 = 0.5
        # z = (0.571429-0.5)/sqrt(0.25/70) = 0.071429/0.059761 = 1.195229
        result = _run(
            two_by_two,
            "proportion_test",
            {"column": "outcome", "success_value": "yes", "p0": 0.5},
        )
        assert result.stats["statistic"] == pytest.approx(1.195229, abs=1e-5)
        assert result.stats["significant_at_0.05"] is False

    def test_unknown_success_value_names_the_real_categories(self, two_by_two):
        with pytest.raises(ExecutionError) as excinfo:
            _run(
                two_by_two,
                "proportion_test",
                {"column": "outcome", "success_value": "maybe", "group_by": "arm"},
            )
        message = str(excinfo.value)
        assert "yes" in message and "no" in message


class TestNormalityTest:
    def test_normal_data_passes(self):
        # A symmetric, well-behaved sample.
        values = [float(v) for v in range(1, 41)]
        df = pd.DataFrame({"x": values})
        result = _run(df, "normality_test", {"column": "x"})
        assert result.stats["overall"]["normal_at_0.05"] is True

    def test_obviously_skewed_data_fails(self):
        df = pd.DataFrame({"x": [1.0] * 30 + [500.0]})
        result = _run(df, "normality_test", {"column": "x"})
        assert result.stats["overall"]["normal_at_0.05"] is False
        assert result.stats["overall"]["skewness"] > 1

    def test_per_group_when_grouped(self, three_groups):
        result = _run(three_groups, "normality_test", {"column": "score", "group_by": "grp"})
        assert len(result.rows) == 3
        assert "shapiro_p" in result.columns


class TestSharedContract:
    """Every Tier 3 result must carry the same reporting surface."""

    @pytest.mark.parametrize(
        "op,params",
        [
            ("ttest", {"kind": "independent", "column": "score", "group_by": "grp"}),
            ("mannwhitney", {"group_by": "grp", "column": "score"}),
        ],
    )
    def test_carries_test_name_p_value_effect_size_and_n(self, two_groups, op, params):
        result = _run(two_groups, op, params)
        assert isinstance(result.stats["test"], str) and result.stats["test"]
        assert 0.0 <= result.stats["p_value"] <= 1.0
        assert "value" in result.stats["effect_size"]
        assert "magnitude" in result.stats["effect_size"]
        assert result.n == 10

    def test_missing_values_are_excluded_and_counted(self, two_groups):
        holed = two_groups.copy()
        holed.loc[0, "score"] = None
        result = _run(holed, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"})
        assert result.n == 9
        assert result.n_excluded == 1
        assert any("Excluded 1 row" in note for note in result.notes)

    def test_degenerate_input_raises_rather_than_returning_nan(self, two_groups):
        single = two_groups.head(1)
        with pytest.raises(ExecutionError):
            _run(single, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"})

    def test_statistics_are_json_safe(self, two_groups):
        import json

        result = _run(
            two_groups, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"}
        )
        encoded = json.dumps(result.stats, allow_nan=False)
        assert "NaN" not in encoded
        assert not math.isnan(result.stats["p_value"])


class TestSmallNumbersSurviveRounding:
    """A p-value rounded to zero claims more than any test can support."""

    def test_a_tiny_p_value_is_not_flattened_to_zero(self):
        # Two well-separated groups of 40 give p on the order of 1e-30.
        df = pd.DataFrame(
            {
                "grp": ["A"] * 40 + ["B"] * 40,
                "score": [float(v) for v in range(40)] + [float(v) for v in range(100, 140)],
            }
        )
        result = _run(df, "ttest", {"kind": "independent", "column": "score", "group_by": "grp"})
        p_value = result.stats["p_value"]
        assert p_value > 0.0
        assert p_value < 1e-20

    def test_paired_drops_are_reported_but_not_as_a_failure(self):
        # Dropping incomplete pairs is correct behaviour, not a violated
        # assumption — flagging it as failed would have the narrator report
        # routine missingness as undermining the result.
        df = pd.DataFrame({"before": [1.0, 2, 3, 4, None], "after": [2.0, 4, 5, 9, 3]})
        result = _run(df, "ttest", {"kind": "paired", "column": "after", "column2": "before"})
        check = _assumption(result, "complete pairs")
        assert check["passed"] is None
        assert "1 incomplete pair" in check["detail"]
        assert result.n_excluded == 1


@pytest.fixture
def mixed_type_groups() -> pd.DataFrame:
    """A grouping column holding both 1 and "1" — what an Excel round-trip gives.

    Five distinct values ({1, "1", 2, "2", "unknown"}) but only three distinct
    labels once stringified. Keying groups by ``str(value)`` while deriving the
    label list from ``unique()`` produces ``['1', '1', '2', '2', 'unknown']``,
    and each duplicate's mask selects every matching row — so eight of the ten
    rows enter the statistic twice.

    Correct one-way ANOVA over the three real groups:
        '1'       -> 10, 90, 12, 88   mean 50
        '2'       -> 20, 30, 22, 33   mean 26.25
        'unknown' -> 15, 18           mean 16.5
        F = 1.057652 on (2, 7) df, p = 0.396866
    """
    return pd.DataFrame(
        {
            "wave": [1, "1", 2, "2", "unknown", 1, "1", 2, "2", "unknown"],
            "score": [10.0, 90.0, 20.0, 30.0, 15.0, 12.0, 88.0, 22.0, 33.0, 18.0],
        }
    )


@pytest.fixture
def mixed_type_equal_spread() -> pd.DataFrame:
    """The duplicated-label shape again, with spreads Levene accepts.

    Groups '1' = 10, 12, 14, 16 | '2' = 20, 22, 24, 26 | 'unknown' = 15, 17.
    """
    return pd.DataFrame(
        {
            "wave": [1, "1", 2, "2", "unknown", 1, "1", 2, "2", "unknown"],
            "score": [10.0, 12.0, 20.0, 22.0, 15.0, 14.0, 16.0, 24.0, 26.0, 17.0],
        }
    )


class TestGroupsAreKeyedOnce:
    """Two values with the same string form must not become two groups.

    A duplicated label makes the same rows enter the statistic twice: the
    degrees of freedom, the sums of squares and the reported ``n`` then
    describe three different datasets.
    """

    def test_anova_sees_three_groups_not_five(self, mixed_type_groups):
        result = _run(mixed_type_groups, "anova", {"group_by": "wave", "column": "score"})
        assert result.stats["df_between"] == 2
        # This fixture's spreads differ, so the omnibus is Welch's — see
        # TestAnovaUnderUnequalVariance. Five groups would make df_between 4
        # whichever test ran.
        assert "3 groups" in result.stats["test"]

    def test_the_arithmetic_is_over_each_row_once(self, mixed_type_equal_spread):
        # Same duplicated-label shape, comparable spreads, so the classic F
        # applies and the whole decomposition is checkable by hand:
        #   means 13 / 23 / 16 about a grand mean of 17.6
        #   SSB = 4(4.6^2) + 4(5.4^2) + 2(1.6^2) = 206.4 on 2 df
        #   SSW = 20 + 20 + 2 = 42 on 7 df   ->  F = 103.2 / 6 = 17.2
        # Counting the eight duplicated rows twice changes every one of these.
        result = _run(mixed_type_equal_spread, "anova", {"group_by": "wave", "column": "score"})
        assert result.stats["df_between"] == 2
        assert result.stats["df_within"] == 7
        assert result.stats["statistic"] == pytest.approx(17.2, abs=1e-9)
        # json_safe rounds to six decimals above 1e-4.
        assert result.stats["p_value"] == pytest.approx(0.001988, abs=1e-6)
        assert result.stats["effect_size"]["value"] == pytest.approx(206.4 / 248.4, abs=1e-6)

    def test_the_summary_table_lists_each_group_once(self, mixed_type_groups):
        result = _run(mixed_type_groups, "anova", {"group_by": "wave", "column": "score"})
        assert [row[0] for row in result.rows] == ["1", "2", "unknown"]
        assert sum(row[1] for row in result.rows) == result.n == 10

    def test_group_sizes_sum_to_the_reported_n(self, mixed_type_groups):
        result = _run(mixed_type_groups, "kruskal", {"group_by": "wave", "column": "score"})
        assert sum(row[1] for row in result.rows) == result.n

    def test_a_single_stringified_group_is_refused_not_self_compared(self):
        # {1, "1"} is ONE group. Two labels would let a Welch t-test compare a
        # group against itself and report t = 0, p = 1 as a real comparison.
        df = pd.DataFrame({"wave": [1, "1", 1, "1"], "score": [1.0, 2.0, 3.0, 4.0]})
        with pytest.raises(ExecutionError, match="needs exactly two groups"):
            _run(df, "ttest", {"kind": "independent", "column": "score", "group_by": "wave"})

    def test_proportion_test_keys_groups_once(self):
        # arm holds both 1 and "1"; with a duplicated label the two-sample test
        # compares arm 1 against itself.
        df = pd.DataFrame(
            {
                "arm": [1, "1", 1, "1", 2, 2, 2, 2],
                "outcome": ["yes", "no", "yes", "no", "yes", "yes", "yes", "no"],
            }
        )
        result = _run(
            df,
            "proportion_test",
            {"column": "outcome", "success_value": "yes", "group_by": "arm"},
        )
        by_group = {row[0]: row for row in result.rows}
        assert set(by_group) == {"1", "2"}
        assert by_group["1"][1] == 4  # n
        assert by_group["1"][2] == 2  # successes
        assert by_group["2"][1] == 4
        assert by_group["2"][2] == 3


@pytest.fixture
def unequal_variance_groups() -> pd.DataFrame:
    """Groups where the classic F and Welch's ANOVA reach opposite conclusions.

    Two large tight groups and one small very wide one — the layout where the
    classic F is anti-conservative. Levene's test rejects equal variance at
    p = 7e-18.

        classic  F = 16.2531 on (2, 85) df,   p < 1e-5   -> "significant"
        Welch    F =  2.7831 on (2, 17.13) df, p = 0.08982 -> not significant

    Both figures were computed independently of this pipeline: the Welch one
    against a hand implementation of Welch (1951) and against
    ``statsmodels.stats.oneway.anova_oneway(use_var="unequal")``, agreeing to
    1e-12.
    """
    rng = numpy.random.default_rng(3)
    a = rng.normal(100, 2, 40)
    b = rng.normal(101, 2, 40)
    c = rng.normal(107, 22, 8)
    return pd.DataFrame({"g": ["a"] * 40 + ["b"] * 40 + ["c"] * 8, "y": numpy.r_[a, b, c]})


class TestAnovaUnderUnequalVariance:
    """When Levene's test fails, the reported test must be the one that applies.

    Surfacing the violation while still handing the narrator the p-value the
    violation invalidates is the silent degradation the scope doc rules out.
    """

    def test_welch_is_reported_when_levene_fails(self, unequal_variance_groups):
        result = _run(unequal_variance_groups, "anova", {"group_by": "g", "column": "y"})
        assert _assumption(result, "equal variance")["passed"] is False
        assert "Welch" in result.stats["test"]
        assert result.stats["statistic"] == pytest.approx(2.7831, abs=1e-4)
        assert result.stats["df_between"] == 2
        assert result.stats["df_within"] == pytest.approx(17.13, abs=1e-2)
        assert result.stats["p_value"] == pytest.approx(0.08982, abs=1e-5)
        assert result.stats["significant_at_0.05"] is False

    def test_the_payload_says_why_welch_was_chosen(self, unequal_variance_groups):
        result = _run(unequal_variance_groups, "anova", {"group_by": "g", "column": "y"})
        assert "variance" in result.stats["test_chosen_because"].lower()
        assert any("Welch" in note for note in result.notes)

    def test_tukey_is_withheld_and_says_so(self, unequal_variance_groups):
        # Tukey's pooled error term is exactly the quantity the failed Levene
        # test says is not shared, so its p-values cannot be shown here.
        result = _run(unequal_variance_groups, "anova", {"group_by": "g", "column": "y"})
        post_hoc = result.stats["post_hoc"]
        assert post_hoc.get("pairs") is None
        assert "Games-Howell" in post_hoc["reason"]

    def test_equal_variance_still_gets_the_classic_f_and_tukey(self, three_groups):
        result = _run(three_groups, "anova", {"group_by": "grp", "column": "score"})
        assert _assumption(result, "equal variance")["passed"] is True
        assert "One-way ANOVA" in result.stats["test"]
        assert "Welch" not in result.stats["test"]
        assert result.stats["statistic"] == pytest.approx(8.0)
        assert result.stats["df_within"] == 12
        assert len(result.stats["post_hoc"]["pairs"]) == 3


class TestWilcoxonReportsThePairsItRanked:
    """The signed-rank test drops zero differences; every field must know that.

    scipy's default ``zero_method="wilcox"`` discards tied pairs before
    ranking. Reporting the count it was handed instead of the count it ranked
    puts three structured fields — n, n_pairs and the completeness check — in
    contradiction with the test that ran.
    """

    @pytest.fixture
    def eight_ties(self) -> pd.DataFrame:
        # 12 complete pairs, 8 of them identical. The test ranks the other 4:
        # all four differences are positive, so W = 0 and p = 2/2**4 = 0.125.
        return pd.DataFrame(
            {
                "before": [5.0, 5, 5, 5, 5, 5, 5, 5, 6, 7, 8, 9],
                "after": [5.0, 5, 5, 5, 5, 5, 5, 5, 4, 5, 6, 7],
            }
        )

    def test_n_pairs_is_what_the_test_ranked(self, eight_ties):
        result = _run(eight_ties, "wilcoxon", {"column": "before", "column2": "after"})
        assert result.stats["statistic"] == 0.0
        assert result.stats["p_value"] == pytest.approx(0.125, abs=1e-9)
        assert result.stats["n_pairs"] == 4
        assert result.stats["n_complete_pairs"] == 12
        assert result.stats["n_tied_pairs"] == 8
        assert result.n == 4
        assert result.n_excluded == 8

    def test_the_completeness_check_counts_the_ties(self, eight_ties):
        result = _run(eight_ties, "wilcoxon", {"column": "before", "column2": "after"})
        check = _assumption(result, "complete pairs")
        assert check["passed"] is not True  # "all 12 pairs complete" would be a lie
        assert "8" in check["detail"] and "4" in check["detail"]

    def test_the_median_and_the_effect_size_name_their_own_denominators(self, eight_ties):
        result = _run(eight_ties, "wilcoxon", {"column": "before", "column2": "after"})
        # Median over all 12 differences is 0 because 8 of them are ties; the
        # effect size is computed on the 4 the test ranked. Both are legitimate
        # and they disagree by construction, so each has to say which set it
        # describes.
        assert result.stats["median_difference"] == pytest.approx(0.0)
        assert "12" in result.stats["median_difference_over"]
        assert result.stats["effect_size"]["value"] == pytest.approx(1.0)
        assert "4" in result.stats["effect_size"]["computed_over"]

    def test_no_ties_still_reports_all_pairs_complete(self):
        df = pd.DataFrame({"a": [1.0, 2, 3, 4, 5, 6], "b": [2.0, 4, 5, 7, 9, 11]})
        result = _run(df, "wilcoxon", {"column": "a", "column2": "b"})
        assert result.stats["n_pairs"] == result.stats["n_complete_pairs"] == 6
        assert result.stats["n_tied_pairs"] == 0
        assert _assumption(result, "complete pairs")["passed"] is True
        assert result.n == 6
        assert result.n_excluded == 0


class TestDirectionalTestsLabelTheirInterval:
    """A one-sided test must not be presented beside an unlabelled two-sided CI.

    At 0.025 < p < 0.05 a directional test rejects while the two-sided interval
    still spans zero. Both numbers are right; unlabelled they read as a
    contradiction, and the narrator is instructed to report the p-value and to
    use the interval.
    """

    @pytest.fixture
    def one_sided_flip(self) -> pd.DataFrame:
        # Seed 13: greater-than p = 0.046201 with a two-sided 95% interval of
        # [-0.149744, 1.904923] — significant, and spanning zero.
        rng = numpy.random.default_rng(13)
        a = rng.normal(0.6, 2, 30)
        b = rng.normal(0.0, 2, 30)
        return pd.DataFrame({"g": ["a"] * 30 + ["b"] * 30, "y": numpy.r_[a, b]})

    def test_the_direction_appears_in_the_test_string(self, one_sided_flip):
        result = _run(
            one_sided_flip,
            "ttest",
            {"kind": "independent", "column": "y", "group_by": "g", "alternative": "greater"},
        )
        assert result.stats["p_value"] == pytest.approx(0.046201, abs=1e-6)
        assert "one-sided" in result.stats["test"]
        assert "greater" in result.stats["test"]

    def test_the_interval_says_it_is_two_sided_and_why_that_can_differ(self, one_sided_flip):
        result = _run(
            one_sided_flip,
            "ttest",
            {"kind": "independent", "column": "y", "group_by": "g", "alternative": "greater"},
        )
        ci = result.stats["confidence_interval"]
        assert ci["low"] == pytest.approx(-0.149744, abs=1e-6)
        assert ci["high"] == pytest.approx(1.904923, abs=1e-6)
        assert ci["sided"] == "two-sided"
        assert "one-sided" in ci["caveat"]

    def test_a_two_sided_test_carries_no_caveat(self, one_sided_flip):
        result = _run(
            one_sided_flip, "ttest", {"kind": "independent", "column": "y", "group_by": "g"}
        )
        ci = result.stats["confidence_interval"]
        assert ci["sided"] == "two-sided"
        assert "caveat" not in ci
        assert "one-sided" not in result.stats["test"]

    @pytest.mark.parametrize(
        ("op", "params"),
        [
            ("ttest", {"kind": "one_sample", "column": "y", "mu": 0.0}),
            ("ttest", {"kind": "paired", "column": "y", "column2": "y2"}),
            ("mannwhitney", {"column": "y", "group_by": "g"}),
            ("wilcoxon", {"column": "y", "column2": "y2"}),
            (
                "proportion_test",
                {"column": "flag", "success_value": "yes", "group_by": "g"},
            ),
            ("proportion_test", {"column": "flag", "success_value": "yes", "p0": 0.5}),
        ],
    )
    def test_every_directional_operation_names_its_direction(self, op, params):
        rng = numpy.random.default_rng(5)
        df = pd.DataFrame(
            {
                "g": ["a"] * 20 + ["b"] * 20,
                "y": rng.normal(1.0, 2, 40),
                "y2": rng.normal(0.0, 2, 40),
                "flag": ["yes", "no"] * 20,
            }
        )
        result = _run(df, op, {**params, "alternative": "greater"})
        assert "one-sided" in result.stats["test"]
        assert "greater" in result.stats["test"]
        ci = result.stats.get("confidence_interval")
        if ci is not None:
            assert ci["sided"] == "two-sided"
            assert "one-sided" in ci["caveat"]


class TestKruskalEffectSizeIsNamedForWhatItComputes:
    """(H - k + 1) / (n - k) is eta squared (rank-based), not epsilon squared.

    Textbook epsilon squared is H / (n - 1). The two differ by roughly 29% on
    the worked example below, enough to land in different magnitude buckets
    around the 0.06 and 0.14 cutoffs. The formula is a legitimate effect size,
    so the name changes rather than the arithmetic.
    """

    @pytest.fixture
    def forty_one_rows(self) -> pd.DataFrame:
        # Three groups, n = 41, k = 3, chosen so H = 7.5358:
        #   code's measure   (H - k + 1) / (n - k) = 5.5358 / 38 = 0.145679
        #   epsilon squared   H / (n - 1)          = 7.5358 / 40 = 0.188395
        rng = numpy.random.default_rng(2)
        return pd.DataFrame(
            {
                "grp": ["A"] * 14 + ["B"] * 14 + ["C"] * 13,
                "score": rng.normal(size=41),
            }
        )

    def test_the_name_matches_the_formula(self, forty_one_rows):
        result = _run(forty_one_rows, "kruskal", {"group_by": "grp", "column": "score"})
        effect = result.stats["effect_size"]
        assert effect["name"] == "eta squared (rank-based)"
        assert "epsilon" not in effect["name"]

    def test_the_value_is_still_the_audited_formula(self, forty_one_rows):
        result = _run(forty_one_rows, "kruskal", {"group_by": "grp", "column": "score"})
        h = result.stats["statistic"]
        n, k = result.n, 3
        assert result.stats["effect_size"]["value"] == pytest.approx(
            (h - k + 1) / (n - k), abs=1e-6
        )
        # And explicitly NOT textbook epsilon squared.
        assert result.stats["effect_size"]["value"] != pytest.approx(h / (n - 1), abs=1e-6)

    def test_the_payload_gives_the_definition(self, forty_one_rows):
        result = _run(forty_one_rows, "kruskal", {"group_by": "grp", "column": "score"})
        assert "(H - k + 1)" in result.stats["effect_size"]["definition"]
