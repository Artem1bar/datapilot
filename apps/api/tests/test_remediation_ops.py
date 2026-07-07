"""The remediation-op subset is defined in code and enforced on agent steps."""

from __future__ import annotations

from pathlib import Path

from app.services.cleaning import REMEDIATION_OPS, supported_operations
from app.services.plan_validator import validate_plan

_EXCLUDED = {
    "convert_time_to_number",
    "standardize_values",
    "flag_contextual_fraud",
    "rename_column",
    "remove_outliers",
}


def test_remediation_ops_is_subset_of_supported():
    assert REMEDIATION_OPS <= supported_operations()


def test_remediation_ops_excludes_restructuring_and_speculative_ops():
    assert _EXCLUDED.isdisjoint(REMEDIATION_OPS)
    # Guard against typos: the excluded names must be real operations.
    assert _EXCLUDED <= supported_operations()


def test_validate_plan_rejects_op_outside_remediation_subset():
    # standardize_values is a real op but not allowed as a remediation step.
    steps = [
        {
            "operation": "standardize_values",
            "column": "x",
            "params": {"mapping": {}},
            "description": "n",
        }
    ]
    issues = validate_plan(steps, set(REMEDIATION_OPS), ["x"])
    assert issues and issues[0].field == "operation"


def test_validate_plan_accepts_remediation_op():
    steps = [
        {
            "operation": "cap_extreme_values",
            "column": "x",
            "params": {"max_value": 100},
            "description": "n",
        }
    ]
    assert validate_plan(steps, set(REMEDIATION_OPS), ["x"]) == []


def test_verification_agent_prompt_has_no_dollar_folklore():
    src = (
        Path(__file__).resolve().parent.parent / "app" / "services" / "verification_agent.py"
    ).read_text(encoding="utf-8")
    for token in ("$50k", "$100k", "gambling"):
        assert token not in src.lower()
