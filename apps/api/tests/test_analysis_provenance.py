"""Provenance — the record that makes a reported number checkable.

An analysis a researcher cannot reconstruct is an analysis they have to take on
faith, which is the thing this pipeline exists not to ask for. These tests pin
the two guarantees: the record names every operation, denominator and library
version behind the answer, and the rendered methods note says plainly that no
figure came from a language model.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import scipy

from app.services.analysis_executor import execute_spec
from app.services.analysis_provenance import (
    build_provenance,
    multiple_comparison_adjustment,
    render_methods_note,
)
from app.services.analysis_result import OperationResult
from app.services.analysis_stats import benjamini_hochberg


@pytest.fixture
def trial() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "arm": ["treatment"] * 6 + ["control"] * 6,
            "score": [12.0, 14, 16, 18, 20, 22, 4, 6, 8, 10, 12, None],
            "responded": ["yes", "yes", "yes", "no", "yes", "no"] * 2,
        }
    )


@pytest.fixture
def spec() -> dict:
    return {
        "rationale": "Compare the two arms and check the response rate.",
        "filter": None,
        "operations": [
            {
                "op": "ttest",
                "label": "Score by arm",
                "params": {"kind": "independent", "column": "score", "group_by": "arm"},
            },
            {
                "op": "proportion_test",
                "label": "Response rate by arm",
                "params": {
                    "column": "responded",
                    "success_value": "yes",
                    "group_by": "arm",
                },
            },
        ],
        "chart": None,
    }


@pytest.fixture
def provenance(trial, spec):
    return build_provenance(
        question="Did the treatment arm do better?",
        spec=spec,
        results=execute_spec(trial, spec),
        df=trial,
        filename="trial.csv",
    )


class TestBenjaminiHochberg:
    def test_uniformly_spaced_p_values(self):
        # p = 0.01..0.05 at m = 5: every adjusted value steps up to 0.05.
        assert benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05]) == pytest.approx(
            [0.05] * 5, abs=1e-9
        )

    def test_one_strong_one_null(self):
        assert benjamini_hochberg([0.001, 0.5]) == pytest.approx([0.002, 0.5], abs=1e-9)

    def test_order_is_preserved_for_unsorted_input(self):
        assert benjamini_hochberg([0.5, 0.001]) == pytest.approx([0.5, 0.002], abs=1e-9)

    def test_adjusted_values_never_exceed_one(self):
        assert all(value <= 1.0 for value in benjamini_hochberg([0.6, 0.7, 0.8]))

    def test_missing_p_values_stay_missing(self):
        assert benjamini_hochberg([0.01, None]) == [0.01, None]

    def test_empty_input(self):
        assert benjamini_hochberg([]) == []


class TestMultipleComparisonAdjustment:
    def test_two_tests_are_adjusted_together(self, trial, spec):
        results = execute_spec(trial, spec)
        adjustment = multiple_comparison_adjustment(results)
        assert adjustment is not None
        assert adjustment["method"] == "Benjamini-Hochberg"
        assert len(adjustment["tests"]) == 2
        for entry in adjustment["tests"]:
            assert entry["p_value_adjusted"] >= entry["p_value"]

    def test_a_single_test_needs_no_adjustment(self, trial, spec):
        one = {**spec, "operations": spec["operations"][:1]}
        assert multiple_comparison_adjustment(execute_spec(trial, one)) is None

    def test_operations_without_a_p_value_are_ignored(self, trial):
        results = execute_spec(
            trial,
            {
                "operations": [
                    {
                        "op": "value_counts",
                        "label": "Arms",
                        "params": {"column": "arm"},
                    },
                    {
                        "op": "value_counts",
                        "label": "Responses",
                        "params": {"column": "responded"},
                    },
                ]
            },
        )
        assert multiple_comparison_adjustment(results) is None


class TestBuildProvenance:
    def test_records_the_question_and_rationale(self, provenance):
        assert provenance["question"] == "Did the treatment arm do better?"
        assert "Compare the two arms" in provenance["rationale"]

    def test_records_the_dataset_shape_it_actually_ran_over(self, provenance):
        assert provenance["dataset"] == {"filename": "trial.csv", "rows": 12, "columns": 3}

    def test_each_operation_carries_its_params_and_denominator(self, provenance):
        first = provenance["operations"][0]
        assert first["op"] == "ttest"
        assert first["params"]["group_by"] == "arm"
        # One score is null, so the t-test ran on 11 of 12 rows.
        assert first["n"] == 11
        assert first["n_excluded"] == 1

    def test_statistics_are_carried_verbatim(self, provenance):
        stats_payload = provenance["operations"][0]["statistics"]
        assert "Welch" in stats_payload["test"]
        assert "effect_size" in stats_payload
        assert stats_payload["assumptions"]

    def test_records_the_library_versions_actually_installed(self, provenance):
        environment = provenance["environment"]
        assert environment["pandas"] == pd.__version__
        assert environment["numpy"] == np.__version__
        assert environment["scipy"] == scipy.__version__
        assert environment["python"].startswith("3.")

    def test_is_json_serializable(self, provenance):
        # It rides along in the chat session's JSON column.
        assert json.loads(json.dumps(provenance, allow_nan=False))

    def test_multiple_comparisons_are_flagged(self, provenance):
        assert provenance["multiple_comparisons"]["method"] == "Benjamini-Hochberg"


class TestMethodsNote:
    def test_names_the_question_data_and_software(self, provenance):
        note = render_methods_note(provenance)
        assert "Did the treatment arm do better?" in note
        assert "12 rows" in note and "trial.csv" in note
        assert f"scipy {scipy.__version__}" in note

    def test_reports_each_test_with_its_denominator(self, provenance):
        note = render_methods_note(provenance)
        assert "Welch" in note
        assert "n = 11" in note
        assert "1 excluded" in note

    def test_surfaces_assumption_checks(self, provenance):
        note = render_methods_note(provenance)
        assert "Assumptions" in note
        assert "variance" in note.lower()

    def test_states_that_no_figure_came_from_a_model(self, provenance):
        # The claim the whole pipeline exists to be able to make.
        note = render_methods_note(provenance)
        assert "language model" in note.lower()

    def test_mentions_the_multiple_comparison_adjustment(self, provenance):
        assert "Benjamini-Hochberg" in render_methods_note(provenance)

    def test_a_filtered_analysis_says_so(self, trial, spec):
        # A number computed over a subset is a different claim from the same
        # number over the whole file, so the note has to name the restriction.
        filtered = {
            **spec,
            "filter": {"column": "arm", "operator": "==", "value": "treatment"},
            "operations": [
                {
                    "op": "ttest",
                    "label": "Treatment scores against 10",
                    "params": {"kind": "one_sample", "column": "score", "mu": 10},
                }
            ],
        }
        note = render_methods_note(
            build_provenance(
                question="Is the treatment arm above 10?",
                spec=filtered,
                results=execute_spec(trial, filtered),
                df=trial,
                filename="trial.csv",
            )
        )
        assert "**Filter.**" in note
        assert "'treatment'" in note


class TestProvenanceSurvivesAFailedOperation:
    """A failed operation must not shift every later operation's parameters.

    ``execute_spec`` drops failures from its result list, so pairing
    ``results[i]`` with ``spec["operations"][i]`` mis-attributes everything
    after the first failure. The methods note exists to let a researcher rerun
    the analysis; parameters belonging to a different operation make it worse
    than nothing.
    """

    @pytest.fixture
    def spec_with_a_failure(self) -> dict:
        return {
            "rationale": "One impossible operation followed by a real one.",
            "operations": [
                {
                    # A t-test over three groups refuses, by design.
                    "op": "ttest",
                    "label": "Impossible comparison",
                    "params": {"kind": "independent", "column": "score", "group_by": "arm"},
                },
                {
                    "op": "groupby_aggregate",
                    "label": "Mean score by arm",
                    "params": {"group_by": ["arm"], "column": "score", "agg": "mean"},
                },
            ],
        }

    @pytest.fixture
    def three_arms(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "arm": ["a", "a", "b", "b", "c", "c"],
                "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        )

    def test_the_surviving_operation_keeps_its_own_parameters(
        self, three_arms, spec_with_a_failure
    ):
        results = execute_spec(three_arms, spec_with_a_failure)
        assert len(results) == 1  # the t-test refused
        record = build_provenance(
            question="q",
            spec=spec_with_a_failure,
            results=results,
            df=three_arms,
            filename="f.csv",
        )
        operation = record["operations"][0]
        assert operation["op"] == "groupby_aggregate"
        assert operation["params"] == {"group_by": ["arm"], "column": "score", "agg": "mean"}
        assert operation["spec_index"] == 1

    def test_the_methods_note_does_not_quote_the_failed_operation(
        self, three_arms, spec_with_a_failure
    ):
        results = execute_spec(three_arms, spec_with_a_failure)
        note = build_provenance(
            question="q",
            spec=spec_with_a_failure,
            results=results,
            df=three_arms,
            filename="f.csv",
        )["methods_note"]
        assert "agg='mean'" in note
        assert "kind='independent'" not in note

    def test_a_spec_without_failures_is_unchanged(self, trial, spec, provenance):
        assert [op["spec_index"] for op in provenance["operations"]] == [0, 1]
        assert provenance["operations"][0]["params"]["kind"] == "independent"
        assert provenance["operations"][1]["params"]["success_value"] == "yes"


def _result(op, label, stats, n=30):
    """A minimal OperationResult carrying a stats payload, for family tests."""
    return OperationResult(
        op=op, label=label, columns=["a", "b"], rows=[["x", 1]], total_rows=1, n=n, stats=stats
    )


class TestTheMultipleComparisonFamily:
    """Which p-values in one answer are corrected together, and which are not.

    The rule is written down in ``analysis_provenance``; these tests pin it.
    Too narrow and the correction misses the tests that most need it; too broad
    and it double-adjusts values that were already corrected, or drags
    diagnostics in beside substantive results.
    """

    def test_correlation_pairs_are_counted(self):
        # Six independent noise columns produce fifteen pairwise tests. Left
        # out of the family, a single correlation_matrix operation produced no
        # correction at all while reporting two "significant" pairs from noise.
        rng = np.random.default_rng(0)
        columns = {name: rng.normal(size=80) for name in "abcdef"}
        results = execute_spec(
            pd.DataFrame(columns),
            {
                "operations": [
                    {
                        "op": "correlation_matrix",
                        "label": "Correlations",
                        "params": {"columns": list("abcdef")},
                    }
                ]
            },
        )
        adjustment = multiple_comparison_adjustment(results)
        assert adjustment is not None
        assert adjustment["n_tests"] == 15

        raw = [pair["p_value"] for pair in results[0].stats["pairs"]]
        assert [entry["p_value"] for entry in adjustment["tests"]] == raw
        assert [entry["p_value_adjusted"] for entry in adjustment["tests"]] == benjamini_hochberg(
            raw
        )

    def test_each_pairwise_entry_names_its_own_pair(self):
        rng = np.random.default_rng(1)
        results = execute_spec(
            pd.DataFrame({name: rng.normal(size=60) for name in "abc"}),
            {
                "operations": [
                    {
                        "op": "correlation_matrix",
                        "label": "Correlations",
                        "params": {"columns": list("abc")},
                    }
                ]
            },
        )
        adjustment = multiple_comparison_adjustment(results)
        labels = [entry["label"] for entry in adjustment["tests"]]
        assert labels == [
            "Correlations — a vs b",
            "Correlations — a vs c",
            "Correlations — b vs c",
        ]

    def test_a_regression_omnibus_test_joins_the_family(self):
        # ols reports its omnibus under f_p_value and logit under llr_p_value.
        # Both are the same claim as an ANOVA's F; excluding them would be an
        # accident of naming.
        results = [
            _result("ttest", "A vs B", {"test": "Welch", "p_value": 0.02}),
            _result("ols", "Model", {"test": "OLS", "f_p_value": 0.01}),
            _result("logit", "Odds", {"test": "Logit", "llr_p_value": 0.004}),
        ]
        adjustment = multiple_comparison_adjustment(results)
        assert adjustment["n_tests"] == 3
        assert [entry["p_value"] for entry in adjustment["tests"]] == [0.02, 0.01, 0.004]

    def test_granger_lags_are_left_out_because_they_self_adjust(self):
        # granger_causality runs Benjamini-Hochberg across its own lags.
        # Benjamini-Hochberg's input must be an unadjusted p-value.
        results = [
            _result("ttest", "A vs B", {"test": "Welch", "p_value": 0.02}),
            _result("ttest", "C vs D", {"test": "Welch", "p_value": 0.3}),
            _result(
                "granger_causality",
                "x -> y",
                {
                    "test": "Granger",
                    "lags": [
                        {"lag": 1, "p_value": 0.01, "p_value_adjusted": 0.02},
                        {"lag": 2, "p_value": 0.2, "p_value_adjusted": 0.2},
                    ],
                },
            ),
        ]
        adjustment = multiple_comparison_adjustment(results)
        assert adjustment["n_tests"] == 2
        assert "x -> y" not in [entry["label"] for entry in adjustment["tests"]]

    def test_diagnostics_are_left_out(self):
        # A normality test asks whether a method applies, not whether something
        # is true of the data; correcting it against a treatment effect inflates
        # both families.
        results = [
            _result("ttest", "A vs B", {"test": "Welch", "p_value": 0.02}),
            _result("ttest", "C vs D", {"test": "Welch", "p_value": 0.3}),
            _result("normality_test", "Is it normal?", {"test": "Shapiro", "p_value": 0.001}),
            _result("stationarity_test", "Unit root?", {"test": "ADF", "p_value": 0.001}),
        ]
        adjustment = multiple_comparison_adjustment(results)
        assert adjustment["n_tests"] == 2

    def test_a_second_presentation_of_one_test_is_not_counted_twice(self):
        # A 2x2 chi-square carries Fisher's exact p beside it, and the survey
        # crosstab carries the naive weighted p it exists to contradict.
        results = [
            _result("ttest", "A vs B", {"test": "Welch", "p_value": 0.02}),
            _result(
                "chi_square",
                "Arm x outcome",
                {"test": "Chi-square", "p_value": 0.03, "fisher_exact": {"p_value": 0.028}},
            ),
            _result(
                "weighted_crosstab",
                "Weighted",
                {"test": "Rao-Scott", "p_value": 0.04, "naive_weighted_p_value": 1e-9},
            ),
        ]
        adjustment = multiple_comparison_adjustment(results)
        assert adjustment["n_tests"] == 3
        assert 0.028 not in [entry["p_value"] for entry in adjustment["tests"]]
        assert 1e-9 not in [entry["p_value"] for entry in adjustment["tests"]]

    def test_a_single_pairwise_correlation_still_needs_no_correction(self):
        results = [
            _result(
                "correlation_matrix",
                "Two columns",
                {"pairs": [{"x": "a", "y": "b", "p_value": 0.04}]},
            )
        ]
        assert multiple_comparison_adjustment(results) is None
