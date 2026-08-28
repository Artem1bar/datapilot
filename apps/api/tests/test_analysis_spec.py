"""Analysis spec validation — the gate between a model's plan and execution.

The validator is the reason the analysis pipeline can be trusted: nothing runs
against user data until it has been checked against a fixed operation set and
the dataframe's real columns and dtypes. These tests pin that gate shut.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.analysis_spec import (
    MAX_OPERATIONS,
    OPERATIONS,
    ColumnRoles,
    describe_capabilities,
    validate_spec,
)


@pytest.fixture
def roles() -> ColumnRoles:
    df = pd.DataFrame(
        {
            "region": ["West", "East"],
            "revenue": [10.0, 20.0],
            "units": [1, 2],
            "order_date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
        }
    )
    return ColumnRoles.from_dataframe(df)


def _spec(**overrides):
    base = {
        "rationale": "because",
        "filter": None,
        "operations": [
            {
                "op": "groupby_aggregate",
                "label": "Revenue by region",
                "params": {"group_by": ["region"], "column": "revenue", "agg": "sum"},
            }
        ],
        "chart": None,
    }
    base.update(overrides)
    return base


class TestColumnRoles:
    def test_classifies_numeric_and_datetime(self, roles):
        assert roles.numeric == {"revenue", "units"}
        assert roles.datetime == {"order_date"}
        assert "region" in roles.all and "region" not in roles.numeric


class TestValidSpecs:
    def test_minimal_spec_passes(self, roles):
        assert validate_spec(_spec(), roles) == []

    def test_refusal_is_valid_and_terminal(self, roles):
        # "This data cannot answer that" is a correct outcome, not a failure.
        assert validate_spec({"refusal": "no income column in this dataset"}, roles) == []

    def test_chart_referencing_a_real_operation(self, roles):
        assert validate_spec(_spec(chart={"type": "bar", "operation": 0}), roles) == []

    def test_filter_passes(self, roles):
        spec = _spec(filter={"column": "region", "operator": "==", "value": "West"})
        assert validate_spec(spec, roles) == []

    def test_null_check_filter_needs_no_value(self, roles):
        spec = _spec(filter={"column": "revenue", "operator": "is_null"})
        assert validate_spec(spec, roles) == []


class TestRejectedSpecs:
    def test_unknown_operation(self, roles):
        spec = _spec(operations=[{"op": "train_neural_net", "params": {}}])
        problems = validate_spec(spec, roles)
        assert any("unknown operation" in p for p in problems)

    def test_hallucinated_column(self, roles):
        spec = _spec(
            operations=[
                {
                    "op": "groupby_aggregate",
                    "params": {"group_by": ["continent"], "column": "revenue", "agg": "sum"},
                }
            ]
        )
        problems = validate_spec(spec, roles)
        assert any("'continent' is not in the dataset" in p for p in problems)

    def test_numeric_aggregation_over_text_column(self, roles):
        # The failure this prevents: mean of a text column, which pandas either
        # refuses or silently produces nonsense for.
        spec = _spec(
            operations=[
                {
                    "op": "groupby_aggregate",
                    "params": {"group_by": ["region"], "column": "region", "agg": "mean"},
                }
            ]
        )
        problems = validate_spec(spec, roles)
        assert any("needs a numeric column" in p for p in problems)

    def test_count_over_text_column_is_allowed(self, roles):
        spec = _spec(
            operations=[
                {
                    "op": "groupby_aggregate",
                    "params": {"group_by": ["region"], "column": "region", "agg": "count"},
                }
            ]
        )
        assert validate_spec(spec, roles) == []

    def test_resample_on_a_text_column_is_rejected(self, roles):
        spec = _spec(
            operations=[
                {
                    "op": "resample",
                    "params": {
                        "date_column": "region",
                        "column": "revenue",
                        "freq": "ME",
                        "agg": "sum",
                    },
                }
            ]
        )
        problems = validate_spec(spec, roles)
        assert any("is not a date/time column" in p for p in problems)

    def test_missing_required_parameter(self, roles):
        spec = _spec(operations=[{"op": "groupby_aggregate", "params": {"group_by": ["region"]}}])
        problems = validate_spec(spec, roles)
        assert any("requires parameter 'column'" in p for p in problems)

    def test_unexpected_parameter(self, roles):
        spec = _spec(
            operations=[
                {
                    "op": "value_counts",
                    "params": {"column": "region", "sql": "DROP TABLE users"},
                }
            ]
        )
        problems = validate_spec(spec, roles)
        assert any("does not accept parameter 'sql'" in p for p in problems)

    def test_correlation_requires_numeric_columns(self, roles):
        spec = _spec(
            operations=[{"op": "correlation_matrix", "params": {"columns": ["revenue", "region"]}}]
        )
        problems = validate_spec(spec, roles)
        assert any("not numeric" in p for p in problems)

    def test_unknown_aggregation(self, roles):
        spec = _spec(
            operations=[
                {
                    "op": "groupby_aggregate",
                    "params": {"group_by": ["region"], "column": "revenue", "agg": "kurtosis"},
                }
            ]
        )
        problems = validate_spec(spec, roles)
        assert any("unknown aggregation" in p for p in problems)

    def test_chart_index_out_of_range(self, roles):
        problems = validate_spec(_spec(chart={"type": "bar", "operation": 7}), roles)
        assert any("out of range" in p for p in problems)

    def test_unknown_chart_type(self, roles):
        problems = validate_spec(_spec(chart={"type": "sankey", "operation": 0}), roles)
        assert any("unknown type" in p for p in problems)

    def test_empty_operations_rejected(self, roles):
        problems = validate_spec(_spec(operations=[]), roles)
        assert any("non-empty list" in p for p in problems)

    def test_too_many_operations(self, roles):
        one = {
            "op": "value_counts",
            "params": {"column": "region"},
        }
        problems = validate_spec(_spec(operations=[one] * (MAX_OPERATIONS + 1)), roles)
        assert any("at most" in p for p in problems)

    def test_unknown_filter_operator(self, roles):
        spec = _spec(filter={"column": "region", "operator": "regex", "value": ".*"})
        problems = validate_spec(spec, roles)
        assert any("unknown operator" in p for p in problems)

    def test_non_object_spec(self, roles):
        assert validate_spec(["not", "a", "spec"], roles)

    def test_all_problems_reported_at_once(self, roles):
        # Collecting every problem means one regeneration round trip, not one
        # per mistake.
        spec = _spec(
            operations=[
                {"op": "groupby_aggregate", "params": {"group_by": ["nope"], "agg": "bogus"}}
            ],
            chart={"type": "sankey", "operation": 9},
        )
        problems = validate_spec(spec, roles)
        assert len(problems) >= 3


class TestCapabilitiesPrompt:
    def test_lists_every_registered_operation(self):
        # Generated from OPERATIONS so the planner prompt cannot drift from
        # what the validator accepts.
        rendered = describe_capabilities()
        for op in OPERATIONS:
            assert op in rendered

    def test_mentions_parameter_names(self):
        rendered = describe_capabilities()
        assert "group_by" in rendered
        assert "optional" in rendered


@pytest.fixture
def survey_roles() -> ColumnRoles:
    """A frame with a low-cardinality outcome, so category checks are live."""
    df = pd.DataFrame(
        {
            "arm": ["treatment", "control", "treatment", "control"],
            "responded": ["yes", "no", "yes", "yes"],
            "score": [1.0, 2.0, 3.0, 4.0],
            "score_after": [2.0, 2.0, 4.0, 4.0],
        }
    )
    return ColumnRoles.from_dataframe(df)


def _op_spec(op, params, **overrides):
    return _spec(operations=[{"op": op, "label": "T", "params": params}], **overrides)


class TestCategoryDiscovery:
    def test_collects_values_of_low_cardinality_text_columns(self, survey_roles):
        assert survey_roles.categories["arm"] == {"treatment", "control"}
        assert survey_roles.categories["responded"] == {"yes", "no"}

    def test_skips_numeric_columns(self, survey_roles):
        # Numbers are not categories; a filter on one is a comparison, not a match.
        assert "score" not in survey_roles.categories

    def test_high_cardinality_columns_are_not_collected(self):
        df = pd.DataFrame({"note": [f"free text {i}" for i in range(200)]})
        assert ColumnRoles.from_dataframe(df).categories == {}

    def test_filter_on_a_value_that_does_not_occur_is_rejected(self, survey_roles):
        # Silently returning zero rows makes every downstream operation fail for
        # reasons that have nothing to do with the question.
        problems = validate_spec(
            _op_spec(
                "value_counts",
                {"column": "responded"},
                filter={"column": "arm", "operator": "==", "value": "Treatment"},
            ),
            survey_roles,
        )
        assert any("has no value" in problem for problem in problems)

    def test_filter_on_a_real_value_passes(self, survey_roles):
        assert (
            validate_spec(
                _op_spec(
                    "value_counts",
                    {"column": "responded"},
                    filter={"column": "arm", "operator": "==", "value": "treatment"},
                ),
                survey_roles,
            )
            == []
        )


class TestTier3Registry:
    def test_every_tier_3_operation_is_registered(self):
        from app.services.analysis_spec import TIER_3

        assert TIER_3 == {
            "ttest",
            "anova",
            "kruskal",
            "mannwhitney",
            "wilcoxon",
            "chi_square",
            "proportion_test",
            "normality_test",
        }

    def test_valid_independent_ttest(self, survey_roles):
        spec = _op_spec("ttest", {"kind": "independent", "column": "score", "group_by": "arm"})
        assert validate_spec(spec, survey_roles) == []

    def test_unknown_kind_is_rejected(self, survey_roles):
        spec = _op_spec("ttest", {"kind": "bootstrap", "column": "score"})
        problems = validate_spec(spec, survey_roles)
        assert any("expected one of" in problem for problem in problems)

    def test_paired_ttest_without_column2_is_rejected(self, survey_roles):
        spec = _op_spec("ttest", {"kind": "paired", "column": "score"})
        problems = validate_spec(spec, survey_roles)
        assert any("column2" in problem for problem in problems)

    def test_parameter_from_another_kind_is_rejected(self, survey_roles):
        # group_by would be dropped at execution, which reads as the test
        # having accounted for it.
        spec = _op_spec(
            "ttest",
            {"kind": "paired", "column": "score", "column2": "score_after", "group_by": "arm"},
        )
        problems = validate_spec(spec, survey_roles)
        assert any("does not apply" in problem for problem in problems)

    def test_ttest_on_a_text_column_is_rejected(self, survey_roles):
        spec = _op_spec("ttest", {"kind": "independent", "column": "responded", "group_by": "arm"})
        assert any("not numeric" in problem for problem in validate_spec(spec, survey_roles))

    def test_chi_square_independence_needs_row(self, survey_roles):
        spec = _op_spec("chi_square", {"kind": "independence", "column": "responded"})
        assert any("requires 'row'" in problem for problem in validate_spec(spec, survey_roles))

    def test_chi_square_goodness_of_fit_rejects_row(self, survey_roles):
        spec = _op_spec(
            "chi_square", {"kind": "goodness_of_fit", "column": "responded", "row": "arm"}
        )
        assert any("drop 'row'" in problem for problem in validate_spec(spec, survey_roles))

    def test_proportion_test_needs_group_by_or_p0(self, survey_roles):
        spec = _op_spec("proportion_test", {"column": "responded", "success_value": "yes"})
        assert any("'p0' is required" in problem for problem in validate_spec(spec, survey_roles))

    def test_proportion_test_rejects_both_group_by_and_p0(self, survey_roles):
        spec = _op_spec(
            "proportion_test",
            {"column": "responded", "success_value": "yes", "group_by": "arm", "p0": 0.5},
        )
        assert any("not both" in problem for problem in validate_spec(spec, survey_roles))

    def test_proportion_test_checks_success_value_against_real_categories(self, survey_roles):
        spec = _op_spec(
            "proportion_test",
            {"column": "responded", "success_value": "Yes", "group_by": "arm"},
        )
        problems = validate_spec(spec, survey_roles)
        assert any("does not occur" in problem for problem in problems)

    def test_p0_must_be_a_proportion(self, survey_roles):
        spec = _op_spec(
            "proportion_test", {"column": "responded", "success_value": "yes", "p0": 50}
        )
        problems = validate_spec(spec, survey_roles)
        assert any("between 0 and 1" in problem for problem in problems)

    def test_valid_two_sample_proportion_test(self, survey_roles):
        spec = _op_spec(
            "proportion_test",
            {"column": "responded", "success_value": "yes", "group_by": "arm"},
        )
        assert validate_spec(spec, survey_roles) == []


class TestCapabilitiesIncludesTier3:
    def test_conditional_rules_reach_the_prompt(self):
        # The planner cannot satisfy a rule it is never told about, and a rule
        # written by hand in the prompt drifts from the validator.
        rendered = describe_capabilities()
        assert "kind=paired needs 'column2'" in rendered
        assert "one_sample|independent|paired" in rendered

    def test_every_operation_declares_a_tier(self):
        rendered = describe_capabilities()
        for op in OPERATIONS:
            assert f"- {op} [tier " in rendered
