"""Tests for pre-execution cleaning plan validation."""

from __future__ import annotations

from app.services.plan_validator import PlanIssue, validate_plan

KNOWN = {
    "clean_column_names",
    "drop_rows",
    "strip_whitespace",
    "cast_type",
    "cap_extreme_values",
    "rename_column",
    "standardize_values",
    "flag_extreme_outliers",
    "fill_null",
    "deduplicate",
}
COLS = ["Amount", "Name\xa0", "City"]


def _step(operation: str, column: str | None = None, **params):
    return {"operation": operation, "column": column, "params": params, "description": "test"}


class TestOperations:
    def test_unknown_operation_flagged(self):
        issues = validate_plan([_step("made_up_op", "Amount")], KNOWN, COLS)
        assert len(issues) == 1
        assert issues[0].field == "operation"
        assert "made_up_op" in issues[0].message

    def test_valid_plan_has_no_issues(self):
        steps = [
            _step("clean_column_names"),
            _step("strip_whitespace", "Name"),
            _step("cast_type", "Amount", target_type="float"),
            _step("deduplicate"),
        ]
        assert validate_plan(steps, KNOWN, COLS) == []

    def test_non_dict_step_flagged(self):
        issues = validate_plan(["not a step"], KNOWN, COLS)
        assert issues and issues[0].field == "operation"


class TestColumns:
    def test_missing_column_flagged(self):
        issues = validate_plan([_step("strip_whitespace", "Nope")], KNOWN, COLS)
        assert issues and issues[0].field == "column"
        assert "Nope" in issues[0].message

    def test_column_required_when_absent(self):
        issues = validate_plan([_step("strip_whitespace")], KNOWN, COLS)
        assert issues and issues[0].field == "column"

    def test_column_optional_ops_accept_null_column(self):
        assert validate_plan([_step("drop_rows", indices=[0])], KNOWN, COLS) == []

    def test_dirty_column_names_match_after_normalization(self):
        # Plan references the cleaned name; dataset still has the NBSP variant
        assert validate_plan([_step("strip_whitespace", "Name")], KNOWN, COLS) == []

    def test_rename_makes_new_name_available_to_later_steps(self):
        steps = [
            _step("rename_column", "City", new_name="Town"),
            _step("strip_whitespace", "Town"),
        ]
        assert validate_plan(steps, KNOWN, COLS) == []

    def test_flag_column_available_after_outlier_step(self):
        steps = [
            _step("flag_extreme_outliers", "Amount"),
            _step("strip_whitespace", "_flagged"),
        ]
        assert validate_plan(steps, KNOWN, COLS) == []


class TestParams:
    def test_missing_required_param_flagged(self):
        issues = validate_plan([_step("cap_extreme_values", "Amount")], KNOWN, COLS)
        assert any(i.field == "params" and "max_value" in i.message for i in issues)

    def test_wrong_param_type_flagged(self):
        issues = validate_plan(
            [_step("cap_extreme_values", "Amount", max_value="lots")], KNOWN, COLS
        )
        assert any("wrong type" in i.message for i in issues)

    def test_negative_drop_rows_indices_flagged(self):
        issues = validate_plan([_step("drop_rows", indices=[-1])], KNOWN, COLS)
        assert any("non-negative" in i.message for i in issues)

    def test_bad_cast_target_flagged(self):
        issues = validate_plan([_step("cast_type", "Amount", target_type="uuid")], KNOWN, COLS)
        assert any("target_type" in i.message for i in issues)

    def test_fill_null_requires_strategy_or_value(self):
        issues = validate_plan([_step("fill_null", "Amount")], KNOWN, COLS)
        assert any("strategy" in i.message for i in issues)

    def test_fill_null_with_value_passes(self):
        assert validate_plan([_step("fill_null", "Amount", value=0)], KNOWN, COLS) == []


def test_issue_str_is_one_based():
    issue = PlanIssue(step_index=0, field="operation", message="x")
    assert str(issue).startswith("Step 1 ")
