"""Analysis execution — every number the user sees originates here.

These tests assert against hand-computed values rather than "a number came
back", because the entire point of the rewrite is that the figures are correct
rather than plausible. Provenance (n, n_excluded, notes) is tested alongside,
since a mean over an unstated denominator is the failure mode this replaced.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from scipy import stats as scipy_stats

from app.services.analysis_executor import (
    MAX_RESULT_ROWS,
    ExecutionError,
    apply_filter,
    build_chart,
    execute_spec,
)


@pytest.fixture
def sales() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["West", "West", "East", "East", "North"],
            "revenue": [100.0, 200.0, 50.0, 70.0, None],
            "units": [1, 2, 3, 4, 5],
            "order_date": pd.to_datetime(
                ["2024-01-05", "2024-01-20", "2024-02-10", "2024-02-25", "2024-03-01"]
            ),
        }
    )


def _run(df, op, params, **spec_extra):
    spec = {"operations": [{"op": op, "label": "T", "params": params}], **spec_extra}
    return execute_spec(df, spec)[0]


class TestGroupbyAggregate:
    def test_sums_are_actually_correct(self, sales):
        result = _run(
            sales, "groupby_aggregate", {"group_by": ["region"], "column": "revenue", "agg": "sum"}
        )
        totals = dict(result.rows)
        assert totals["West"] == 300.0  # 100 + 200
        assert totals["East"] == 120.0  # 50 + 70

    def test_null_target_rows_are_excluded_and_reported(self, sales):
        # North's only revenue is null — it must not appear as 0.
        result = _run(
            sales, "groupby_aggregate", {"group_by": ["region"], "column": "revenue", "agg": "sum"}
        )
        assert "North" not in dict(result.rows)
        assert result.n_excluded == 1
        assert any("Excluded 1 row" in n for n in result.notes)

    def test_count_keeps_null_targets(self, sales):
        # count is meaningful over nulls, so North survives.
        result = _run(
            sales,
            "groupby_aggregate",
            {"group_by": ["region"], "column": "revenue", "agg": "count"},
        )
        assert "North" in dict(result.rows)

    def test_mean_is_correct(self, sales):
        result = _run(
            sales, "groupby_aggregate", {"group_by": ["region"], "column": "revenue", "agg": "mean"}
        )
        assert dict(result.rows)["West"] == 150.0

    def test_all_null_target_raises(self):
        df = pd.DataFrame({"g": ["a", "b"], "v": [None, None]})
        with pytest.raises(ExecutionError, match="no rows remain"):
            _run(df, "groupby_aggregate", {"group_by": ["g"], "column": "v", "agg": "sum"})


class TestValueCounts:
    def test_counts_are_correct(self, sales):
        result = _run(sales, "value_counts", {"column": "region"})
        counts = dict(result.rows)
        assert counts["West"] == 2
        assert counts["North"] == 1

    def test_top_n_limits_rows(self, sales):
        result = _run(sales, "value_counts", {"column": "region", "top_n": 1})
        assert len(result.rows) == 1

    def test_normalize_produces_proportions(self, sales):
        result = _run(sales, "value_counts", {"column": "region", "normalize": True})
        assert result.columns[1] == "proportion"
        assert dict(result.rows)["West"] == pytest.approx(0.4)


class TestHistogram:
    def test_bin_counts_sum_to_non_null_rows(self, sales):
        result = _run(sales, "histogram", {"column": "revenue", "bins": 4})
        assert sum(row[1] for row in result.rows) == 4  # 5 rows, 1 null
        assert result.n_excluded == 1

    def test_all_null_raises(self):
        df = pd.DataFrame({"v": [None, None]})
        with pytest.raises(ExecutionError, match="no non-null values"):
            _run(df, "histogram", {"column": "v"})


class TestTopN:
    def test_returns_highest_by_default(self, sales):
        result = _run(sales, "top_n", {"column": "region", "by": "revenue", "n": 1})
        assert result.rows[0][1] == 200.0

    def test_ascending_returns_lowest(self, sales):
        result = _run(
            sales, "top_n", {"column": "region", "by": "revenue", "n": 1, "ascending": True}
        )
        assert result.rows[0][1] == 50.0


class TestCorrelationMatrix:
    def test_perfect_correlation_is_one(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4], "b": [2, 4, 6, 8]})
        result = _run(df, "correlation_matrix", {"columns": ["a", "b"]})
        pair = result.stats["pairs"][0]
        assert pair["r"] == pytest.approx(1.0)
        assert pair["p_value"] < 0.05

    def test_reports_p_values(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"a": rng.normal(size=60), "b": rng.normal(size=60)})
        result = _run(df, "correlation_matrix", {"columns": ["a", "b"]})
        # Independent noise: a p-value must be present so the narrator can say
        # the correlation is not distinguishable from zero.
        assert "p_value" in result.stats["pairs"][0]

    def test_too_few_rows_raises(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [2.0, 4.0]})
        with pytest.raises(ExecutionError, match="need at least 3"):
            _run(df, "correlation_matrix", {"columns": ["a", "b"]})

    def test_spearman_method_is_honoured(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4], "b": [1, 4, 9, 16]})
        result = _run(df, "correlation_matrix", {"columns": ["a", "b"], "method": "spearman"})
        assert result.stats["method"] == "spearman"
        assert result.stats["pairs"][0]["r"] == pytest.approx(1.0)  # monotonic


class TestScatterWithFit:
    def test_recovers_a_known_line(self):
        # y = 3x + 5 exactly; the fit must find it.
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [8.0, 11.0, 14.0, 17.0]})
        result = _run(df, "scatter_with_fit", {"x": "x", "y": "y"})
        assert result.stats["slope"] == pytest.approx(3.0)
        assert result.stats["intercept"] == pytest.approx(5.0)
        assert result.stats["r_squared"] == pytest.approx(1.0)

    def test_reports_the_fit_as_text(self):
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0, 6.0]})
        result = _run(df, "scatter_with_fit", {"x": "x", "y": "y"})
        assert "y = " in result.stats["fit"]


class TestGroupComparison:
    def test_reports_means_and_confidence_intervals(self):
        df = pd.DataFrame(
            {"g": ["a"] * 5 + ["b"] * 5, "v": [1.0, 2, 3, 4, 5, 10.0, 11, 12, 13, 14]}
        )
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        assert "ci95_low" in result.columns
        assert "ci95_high" in result.columns
        by_group = {row[0]: row for row in result.rows}
        assert by_group["a"][2] == pytest.approx(3.0)  # mean of 1..5

    def test_two_groups_run_a_welch_t_test(self):
        df = pd.DataFrame(
            {"g": ["a"] * 5 + ["b"] * 5, "v": [1.0, 2, 3, 4, 5, 10.0, 11, 12, 13, 14]}
        )
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        assert "Welch" in result.stats["test"]
        assert result.stats["p_value"] < 0.05  # clearly separated groups

    def test_three_groups_run_anova(self):
        df = pd.DataFrame({"g": ["a", "a", "b", "b", "c", "c"], "v": [1.0, 2, 5, 6, 9, 10]})
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        # The test string names what was compared; see
        # TestGroupComparisonNamesWhatItCompared for why.
        assert result.stats["test"] == "one-way ANOVA across 3 groups (a, b, c)"

    def test_identical_groups_are_not_significant(self):
        df = pd.DataFrame({"g": ["a"] * 5 + ["b"] * 5, "v": [1.0, 2, 3, 4, 5] * 2})
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        assert result.stats["p_value"] > 0.05


class TestCrosstab:
    def test_counts_are_correct(self):
        df = pd.DataFrame({"a": ["x", "x", "y", "y"], "b": ["p", "q", "p", "q"]})
        result = _run(df, "crosstab", {"row": "a", "column": "b"})
        assert result.total_rows == 2

    def test_runs_chi_square_when_shape_allows(self):
        df = pd.DataFrame({"a": ["x", "x", "y", "y"] * 10, "b": ["p", "q", "p", "q"] * 10})
        result = _run(df, "crosstab", {"row": "a", "column": "b"})
        assert "chi-square" in result.stats["test"]
        assert "p_value" in result.stats


class TestResample:
    def test_monthly_totals_are_correct(self, sales):
        result = _run(
            sales,
            "resample",
            {"date_column": "order_date", "column": "revenue", "freq": "ME", "agg": "sum"},
        )
        totals = [row[1] for row in result.rows]
        assert 300.0 in totals  # January: 100 + 200
        assert 120.0 in totals  # February: 50 + 70


class TestFilter:
    def test_equality_filter(self, sales):
        filtered, note = apply_filter(
            sales, {"column": "region", "operator": "==", "value": "West"}
        )
        assert len(filtered) == 2
        assert "Filtered to rows" in note

    def test_numeric_comparison(self, sales):
        filtered, _ = apply_filter(sales, {"column": "revenue", "operator": ">", "value": 60})
        assert len(filtered) == 3  # 100, 200, 70

    def test_contains_is_case_insensitive(self, sales):
        filtered, _ = apply_filter(
            sales, {"column": "region", "operator": "contains", "value": "wes"}
        )
        assert len(filtered) == 2

    def test_is_null(self, sales):
        filtered, _ = apply_filter(sales, {"column": "revenue", "operator": "is_null"})
        assert len(filtered) == 1

    def test_non_numeric_value_for_numeric_operator_raises(self, sales):
        with pytest.raises(ExecutionError, match="not numeric"):
            apply_filter(sales, {"column": "revenue", "operator": ">", "value": "abc"})

    def test_no_filter_is_a_passthrough(self, sales):
        filtered, note = apply_filter(sales, None)
        assert len(filtered) == len(sales)
        assert note is None

    def test_filter_note_is_attached_to_results(self, sales):
        results = execute_spec(
            sales,
            {
                "filter": {"column": "region", "operator": "==", "value": "West"},
                "operations": [
                    {"op": "value_counts", "label": "T", "params": {"column": "region"}}
                ],
            },
        )
        assert any("Filtered to rows" in n for n in results[0].notes)


class TestExecuteSpec:
    def test_partial_failure_still_returns_working_operations(self, sales):
        spec = {
            "operations": [
                {"op": "value_counts", "label": "ok", "params": {"column": "region"}},
                # histogram over an all-null column fails at runtime
                {"op": "histogram", "label": "bad", "params": {"column": "missing_col"}},
            ]
        }
        results = execute_spec(sales, spec)
        assert len(results) == 1
        assert any("failed" in n for n in results[0].notes)

    def test_total_failure_raises(self, sales):
        spec = {"operations": [{"op": "histogram", "label": "bad", "params": {"column": "nope"}}]}
        with pytest.raises(ExecutionError):
            execute_spec(sales, spec)

    def test_results_are_capped(self):
        df = pd.DataFrame({"g": [f"g{i}" for i in range(MAX_RESULT_ROWS + 50)]})
        result = _run(df, "value_counts", {"column": "g", "top_n": MAX_RESULT_ROWS + 50})
        assert len(result.rows) == MAX_RESULT_ROWS
        assert result.total_rows == MAX_RESULT_ROWS + 50
        assert any("Showing the first" in n for n in result.notes)


class TestBuildChart:
    def test_chart_data_comes_from_the_computed_result(self, sales):
        results = execute_spec(
            sales,
            {
                "operations": [
                    {
                        "op": "groupby_aggregate",
                        "label": "Revenue by region",
                        "params": {"group_by": ["region"], "column": "revenue", "agg": "sum"},
                    }
                ]
            },
        )
        chart = build_chart({"type": "bar", "operation": 0}, results)
        assert chart is not None
        # The plotted values must be the measured values, not a model's guess.
        plotted = {point["x"]: point["y"] for point in chart["data"]}
        assert plotted["West"] == 300.0
        assert chart["options"]["computed"] is True

    def test_group_comparison_charts_means_not_counts(self):
        # Regression: the naive "column 1" default plotted group SIZES under a
        # title promising averages, because group_comparison returns
        # [group, count, mean, std, ...].
        df = pd.DataFrame({"g": ["a"] * 5 + ["b"] * 3, "v": [10.0] * 5 + [20.0] * 3})
        results = execute_spec(
            df,
            {
                "operations": [
                    {
                        "op": "group_comparison",
                        "label": "Average v by group",
                        "params": {"group_by": "g", "column": "v"},
                    }
                ]
            },
        )
        chart = build_chart({"type": "bar", "operation": 0}, results)
        assert chart is not None
        assert chart["y_field"] == "mean"
        plotted = {point["x"]: point["y"] for point in chart["data"]}
        assert plotted["a"] == pytest.approx(10.0)  # the mean, not the count of 5
        assert plotted["b"] == pytest.approx(20.0)

    def test_spec_can_name_the_y_column(self):
        df = pd.DataFrame({"g": ["a"] * 5 + ["b"] * 3, "v": [10.0] * 5 + [20.0] * 3})
        results = execute_spec(
            df,
            {
                "operations": [
                    {
                        "op": "group_comparison",
                        "label": "T",
                        "params": {"group_by": "g", "column": "v"},
                    }
                ]
            },
        )
        chart = build_chart({"type": "bar", "operation": 0, "y": "count"}, results)
        assert chart["y_field"] == "count"
        assert {p["x"]: p["y"] for p in chart["data"]}["a"] == 5

    def test_unknown_y_column_falls_back(self, sales):
        results = execute_spec(
            sales,
            {
                "operations": [
                    {
                        "op": "groupby_aggregate",
                        "label": "T",
                        "params": {"group_by": ["region"], "column": "revenue", "agg": "sum"},
                    }
                ]
            },
        )
        chart = build_chart({"type": "bar", "operation": 0, "y": "not_a_column"}, results)
        assert chart is not None
        assert chart["y_field"] == "revenue_sum"

    def test_returns_none_without_a_chart_spec(self, sales):
        results = execute_spec(
            sales,
            {"operations": [{"op": "value_counts", "label": "T", "params": {"column": "region"}}]},
        )
        assert build_chart(None, results) is None

    def test_returns_none_for_out_of_range_index(self, sales):
        results = execute_spec(
            sales,
            {"operations": [{"op": "value_counts", "label": "T", "params": {"column": "region"}}]},
        )
        assert build_chart({"type": "bar", "operation": 5}, results) is None


class TestDegenerateStatistics:
    def test_zero_variance_groups_report_no_test_instead_of_nan(self):
        # scipy returns NaN here, and NaN is not valid JSON — the API would
        # emit something no parser accepts.
        df = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 4, "v": [10.0] * 8})
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        assert result.stats["test"] == "not computed"
        assert "zero variance" in result.stats["reason"]

    def test_every_stats_payload_is_strictly_json_serializable(self):
        # allow_nan=False is what a JSON API must be able to emit.
        df = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 4, "v": [10.0] * 8})
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        json.dumps(result.stats, allow_nan=False)
        json.dumps(result.to_table(), allow_nan=False)


class TestJSONSafety:
    def test_nan_and_inf_become_null(self):
        df = pd.DataFrame({"g": ["a", "b"], "v": [float("inf"), 1.0]})
        result = _run(df, "top_n", {"column": "g", "by": "v", "n": 2})
        # inf is not JSON-serializable; it must come back as None, not crash.
        assert None in [row[1] for row in result.rows]

    def test_timestamps_are_isoformat_strings(self, sales):
        result = _run(
            sales,
            "resample",
            {"date_column": "order_date", "column": "revenue", "freq": "ME", "agg": "sum"},
        )
        assert isinstance(result.rows[0][0], str)
        assert "2024-01" in result.rows[0][0]


class TestTinyPValuesKeepSignificantFigures:
    """A p-value below 1e-6 must not serialize as 0.0.

    ``json_safe`` keeps significant figures below 1e-4 precisely so that a
    vanishingly small p-value reads as vanishingly small. Rounding to six
    decimal places before it gets there throws the figure away and prints
    p = 0 — a claim of certainty no test can support — which then reaches the
    narrator, the methods note and the Benjamini-Hochberg input.
    """

    def test_group_comparison_keeps_a_1e14_p_value(self):
        rng = np.random.default_rng(3)
        values = np.r_[rng.normal(0, 1, 30), rng.normal(3, 1, 30)]
        df = pd.DataFrame({"g": ["A"] * 30 + ["B"] * 30, "y": values})

        # Independently: scipy's own Welch t-test on the same two groups.
        expected = float(scipy_stats.ttest_ind(values[:30], values[30:], equal_var=False).pvalue)
        assert expected == pytest.approx(1.94018e-14, rel=1e-4)

        result = _run(df, "group_comparison", {"group_by": "g", "column": "y"})
        assert result.stats["p_value"] != 0.0
        assert result.stats["p_value"] == pytest.approx(expected, rel=1e-5, abs=0.0)

    def test_group_comparison_anova_keeps_a_tiny_p_value(self):
        rng = np.random.default_rng(11)
        values = np.r_[rng.normal(0, 1, 30), rng.normal(4, 1, 30), rng.normal(8, 1, 30)]
        df = pd.DataFrame({"g": ["A"] * 30 + ["B"] * 30 + ["C"] * 30, "y": values})

        expected = float(scipy_stats.f_oneway(values[:30], values[30:60], values[60:]).pvalue)
        assert expected < 1e-6

        result = _run(df, "group_comparison", {"group_by": "g", "column": "y"})
        assert result.stats["p_value"] != 0.0
        assert result.stats["p_value"] == pytest.approx(expected, rel=1e-5, abs=0.0)

    def test_scatter_with_fit_keeps_a_tiny_slope_p_value(self):
        # Noisy rather than exact: a perfect fit underflows scipy's own
        # p-value to 0.0, which would test scipy instead of this rounding.
        x = np.arange(200, dtype=float)
        y = 2 * x + np.random.default_rng(7).normal(0, 40, 200)
        df = pd.DataFrame({"x": x, "y": y})

        expected = float(scipy_stats.linregress(x, y).pvalue)
        assert expected == pytest.approx(2.0661e-111, rel=1e-4, abs=0.0)

        result = _run(df, "scatter_with_fit", {"x": "x", "y": "y"})
        assert result.stats["p_value"] != 0.0
        assert result.stats["p_value"] == pytest.approx(expected, rel=1e-5, abs=0.0)

    def test_correlation_pairs_keep_a_tiny_p_value(self):
        x = np.arange(200, dtype=float)
        y = 2 * x + np.random.default_rng(7).normal(0, 40, 200)
        df = pd.DataFrame({"a": x, "b": y})

        expected = float(scipy_stats.pearsonr(x, y).pvalue)
        assert expected == pytest.approx(2.0661e-111, rel=1e-4, abs=0.0)

        result = _run(df, "correlation_matrix", {"columns": ["a", "b"]})
        assert result.stats["pairs"][0]["p_value"] != 0.0
        assert result.stats["pairs"][0]["p_value"] == pytest.approx(expected, rel=1e-5, abs=0.0)

    def test_crosstab_chi_square_keeps_a_tiny_p_value(self):
        # 200 rows, perfectly associated: chi-square is enormous and p is tiny.
        df = pd.DataFrame({"r": ["u", "v"] * 100, "c": ["yes", "no"] * 100})
        table = pd.crosstab(df["r"], df["c"])
        expected = float(scipy_stats.chi2_contingency(table).pvalue)
        assert expected < 1e-6

        result = _run(df, "crosstab", {"row": "r", "column": "c"})
        assert result.stats["p_value"] != 0.0
        assert result.stats["p_value"] == pytest.approx(expected, rel=1e-5, abs=0.0)


class TestGroupComparisonNamesWhatItCompared:
    """A group too small to test must not vanish between the table and the test.

    ``group_comparison`` filters groups with a single observation out of the
    significance test — correctly, since one value contributes no variance —
    but the summary table and the chart still show them. The result has to say
    which groups the test used, which it did not, and over how many rows.
    """

    @pytest.fixture
    def one_singleton(self) -> pd.DataFrame:
        # A and B are six rows each; C is a single outlying row.
        # Welch's t on A vs B alone: t = -11.3747, p = 4.82427e-07.
        return pd.DataFrame(
            {
                "segment": ["A"] * 6 + ["B"] * 6 + ["C"],
                "spend": [10, 12, 11, 13, 9, 12, 20, 22, 21, 19, 23, 20, 400],
            }
        )

    def test_the_test_string_names_the_compared_groups(self, one_singleton):
        result = _run(one_singleton, "group_comparison", {"group_by": "segment", "column": "spend"})
        assert "A" in result.stats["test"] and "B" in result.stats["test"]
        assert result.stats["groups_compared"] == ["A", "B"]
        assert result.stats["groups_excluded"] == ["C"]

    def test_n_is_the_rows_the_test_used(self, one_singleton):
        result = _run(one_singleton, "group_comparison", {"group_by": "segment", "column": "spend"})
        assert result.n == 12  # A (6) + B (6); C's single row is not in the test
        assert result.n_excluded == 1
        assert any("C" in note for note in result.notes)

    def test_the_statistic_is_still_the_two_group_welch_t(self, one_singleton):
        result = _run(one_singleton, "group_comparison", {"group_by": "segment", "column": "spend"})
        expected = scipy_stats.ttest_ind(
            one_singleton.spend[:6], one_singleton.spend[6:12], equal_var=False
        )
        assert result.stats["statistic"] == pytest.approx(float(expected.statistic), abs=1e-4)
        assert result.stats["p_value"] == pytest.approx(float(expected.pvalue), rel=1e-5, abs=0.0)

    def test_the_summary_table_still_shows_every_group(self, one_singleton):
        result = _run(one_singleton, "group_comparison", {"group_by": "segment", "column": "spend"})
        assert [row[0] for row in result.rows] == ["A", "B", "C"]

    def test_two_singletons_leave_one_group_and_say_no_test_ran(self):
        df = pd.DataFrame(
            {"segment": ["A"] * 6 + ["B"] + ["C"], "spend": [10, 12, 11, 13, 9, 12, 500, 900]}
        )
        result = _run(df, "group_comparison", {"group_by": "segment", "column": "spend"})
        assert result.stats["test"] == "not computed"
        assert "B" in result.stats["reason"] and "C" in result.stats["reason"]
        assert result.stats.get("p_value") is None

    def test_four_groups_with_a_singleton_run_anova_over_three(self):
        df = pd.DataFrame(
            {
                "g": ["a", "a", "b", "b", "c", "c", "d"],
                "v": [1.0, 2, 5, 6, 9, 10, 99],
            }
        )
        result = _run(df, "group_comparison", {"group_by": "g", "column": "v"})
        assert "ANOVA" in result.stats["test"]
        assert result.stats["groups_compared"] == ["a", "b", "c"]
        assert result.stats["groups_excluded"] == ["d"]
        assert result.n == 6
        assert result.n_excluded == 1


class TestCrosstabAndPivotReportTheirRealDenominator:
    """pandas drops null keys; the result has to say so.

    ``pd.crosstab`` and ``pd.pivot_table`` silently exclude rows null in any
    column they use, and a chi-square p-value was being attached to the
    overstated denominator. The narrator prompt asks for excluded rows to be
    stated — here it was being told there were none.
    """

    @pytest.fixture
    def with_nulls(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "arm": ["x"] * 40 + ["y"] * 40 + [None] * 20,
                "outcome": ["p", "q"] * 50,
                "revenue": [1.0] * 90 + [None] * 10,
            }
        )

    def test_crosstab_n_is_the_rows_the_table_covers(self, with_nulls):
        result = _run(with_nulls, "crosstab", {"row": "arm", "column": "outcome"})
        assert result.n == 80
        assert result.n_excluded == 20
        assert any("20" in note for note in result.notes)
        assert sum(sum(row[1:]) for row in result.rows) == 80

    def test_crosstab_chi_square_matches_the_stated_n(self, with_nulls):
        result = _run(with_nulls, "crosstab", {"row": "arm", "column": "outcome"})
        complete = with_nulls.dropna(subset=["arm", "outcome"])
        expected = scipy_stats.chi2_contingency(pd.crosstab(complete["arm"], complete["outcome"]))
        assert result.stats["chi2"] == pytest.approx(float(expected.statistic), abs=1e-4)
        assert result.n == len(complete)

    def test_pivot_n_is_the_rows_it_aggregated(self, with_nulls):
        result = _run(
            with_nulls,
            "pivot",
            {"index": ["arm"], "columns": "outcome", "values": "revenue", "agg": "sum"},
        )
        # 20 rows have a null arm; of the remaining 80, none has a null
        # revenue (the nulls are in rows 90-99, which also have a null arm).
        assert result.n == 80
        assert result.n_excluded == 20
        assert any("20" in note for note in result.notes)

    def test_pivot_drops_null_values_for_numeric_aggregations(self):
        df = pd.DataFrame(
            {
                "arm": ["x", "y"] * 10,
                "outcome": ["p", "q"] * 10,
                "revenue": [1.0] * 15 + [None] * 5,
            }
        )
        result = _run(
            df, "pivot", {"index": ["arm"], "columns": "outcome", "values": "revenue", "agg": "sum"}
        )
        assert result.n == 15
        assert result.n_excluded == 5

    def test_a_clean_frame_still_reports_every_row(self):
        df = pd.DataFrame({"a": ["x", "y"] * 10, "b": ["p", "q"] * 10})
        result = _run(df, "crosstab", {"row": "a", "column": "b"})
        assert result.n == 20
        assert result.n_excluded == 0
        assert result.notes == []


class TestChartTargetsTheSpecOperation:
    """``chart.operation`` names a spec index, not a position in the results.

    Failures are dropped from the result list, so indexing it positionally
    plots a different operation than the one the chart config asked for, or
    drops the chart entirely.
    """

    @pytest.fixture
    def spec_with_a_failure(self) -> dict:
        return {
            "operations": [
                {
                    # Refuses: a two-group t-test over three groups.
                    "op": "ttest",
                    "label": "Impossible comparison",
                    "params": {"kind": "independent", "column": "v", "group_by": "g"},
                },
                {
                    "op": "groupby_aggregate",
                    "label": "Mean v by g",
                    "params": {"group_by": ["g"], "column": "v", "agg": "mean"},
                },
            ],
            "chart": {"type": "bar", "operation": 1},
        }

    @pytest.fixture
    def three_groups(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"g": ["a", "a", "b", "b", "c", "c"], "v": [1.0, 3.0, 5.0, 7.0, 9.0, 11.0]}
        )

    def test_the_chart_finds_its_operation_after_an_earlier_failure(
        self, three_groups, spec_with_a_failure
    ):
        results = execute_spec(three_groups, spec_with_a_failure)
        assert len(results) == 1
        chart = build_chart(spec_with_a_failure["chart"], results)
        assert chart is not None
        assert chart["title"] == "Mean v by g"
        assert {point["x"]: point["y"] for point in chart["data"]} == {
            "a": 2.0,
            "b": 6.0,
            "c": 10.0,
        }

    def test_a_chart_pointing_at_a_failed_operation_is_dropped(self, three_groups):
        spec = {
            "operations": [
                {
                    "op": "ttest",
                    "label": "Impossible comparison",
                    "params": {"kind": "independent", "column": "v", "group_by": "g"},
                },
                {
                    "op": "groupby_aggregate",
                    "label": "Mean v by g",
                    "params": {"group_by": ["g"], "column": "v", "agg": "mean"},
                },
            ],
            "chart": {"type": "bar", "operation": 0},
        }
        results = execute_spec(three_groups, spec)
        # Operation 0 did not survive, so there is nothing honest to plot.
        assert build_chart(spec["chart"], results) is None

    def test_results_carry_their_spec_index(self, three_groups, spec_with_a_failure):
        results = execute_spec(three_groups, spec_with_a_failure)
        assert results[0].spec_index == 1


class TestMinorEdgeCases:
    def test_top_n_by_its_own_column(self):
        # "top 10 revenues by revenue" is a plausible plan and the validator
        # permits it. df[[c, c]] makes a duplicate column and dropna(subset=[c])
        # then raises "The column label is not unique", so the operation was
        # silently dropped from the answer.
        df = pd.DataFrame({"revenue": [10.0, 50.0, None, 30.0]})
        result = _run(df, "top_n", {"column": "revenue", "by": "revenue", "n": 2})
        assert [row[0] for row in result.rows] == [50.0, 30.0]
        assert result.n == 3
        assert result.n_excluded == 1

    def test_not_equal_filter_says_that_it_keeps_nulls(self):
        # pandas semantics: NaN != 'x' is True, so "!=" keeps rows whose value
        # is missing while "==" drops them. The behaviour is left alone (the
        # code export reproduces it exactly) but the note now says so, because
        # it changes the denominator of everything downstream.
        df = pd.DataFrame({"c": ["x", "y", None, "x"], "v": [1, 2, 3, 4]})
        kept, note = apply_filter(df, {"column": "c", "operator": "!=", "value": "x"})
        assert list(kept["v"]) == [2, 3]
        assert "missing" in note

    def test_equality_filter_note_is_unchanged(self):
        df = pd.DataFrame({"c": ["x", "y", None, "x"], "v": [1, 2, 3, 4]})
        kept, note = apply_filter(df, {"column": "c", "operator": "==", "value": "x"})
        assert list(kept["v"]) == [1, 4]
        assert "missing" not in note

    def test_not_equal_filter_on_a_clean_column_says_nothing_extra(self):
        df = pd.DataFrame({"c": ["x", "y"], "v": [1, 2]})
        _, note = apply_filter(df, {"column": "c", "operator": "!=", "value": "x"})
        assert "missing" not in note
