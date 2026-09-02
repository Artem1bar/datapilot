"""Tests for the Claude verification agent service (forced tool use)."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

from app.config import settings
from app.services.verification_agent import (
    AgentVerificationResult,
    _result_from_tool_input,
    run_verification_agent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(payload: dict) -> MagicMock:
    """Build a mock Anthropic response whose content is a submit_verification tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_verification"
    block.id = "toolu_verify"
    block.input = payload
    response = MagicMock()
    response.content = [block]
    return response


def _text_only_response(text: str = "I could not verify.") -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _valid_agent_json(**overrides) -> dict:
    """Return a valid agent tool-input dict with optional overrides."""
    base = {
        "passed": True,
        "confidence": 0.95,
        "issues_found": [],
        "recommendations": ["Looks good"],
        "remediation_steps": [],
        "summary": "All cleaning steps verified successfully.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _result_from_tool_input tests
# ---------------------------------------------------------------------------


class TestResultFromToolInput:
    def test_builds_result_from_valid_input(self):
        result = _result_from_tool_input(_valid_agent_json())

        assert isinstance(result, AgentVerificationResult)
        assert result.passed is True
        assert result.confidence == 0.95
        assert result.issues_found == ()
        assert result.recommendations == ("Looks good",)
        assert result.summary == "All cleaning steps verified successfully."

    def test_missing_fields_fall_back_to_defaults(self):
        result = _result_from_tool_input({})

        assert result.passed is False
        assert result.confidence == 0.0
        assert result.issues_found == ()
        assert result.recommendations == ()
        assert result.remediation_steps == ()
        assert result.summary == ""

    def test_carries_remediation_and_issues(self):
        result = _result_from_tool_input(
            _valid_agent_json(
                passed=False,
                remediation_steps=[{"operation": "cap_extreme_values", "column": "Hotel"}],
                issues_found=[{"column": "Hotel", "issue": "outlier", "severity": "CRITICAL"}],
            )
        )

        assert result.passed is False
        assert result.remediation_steps[0]["operation"] == "cap_extreme_values"
        assert result.issues_found[0]["severity"] == "CRITICAL"

    def test_non_numeric_confidence_does_not_raise(self):
        # A non-numeric confidence from the (non-strict) tool call must degrade
        # to 0.0, not raise — otherwise the verification round is silently lost.
        result = _result_from_tool_input(_valid_agent_json(confidence="not a number"))
        assert result.confidence == 0.0

    def test_out_of_range_confidence_is_clamped(self):
        # 150 (a percentage) normalizes and clamps into [0, 1] rather than
        # rendering as "15000% confidence".
        result = _result_from_tool_input(_valid_agent_json(confidence=150))
        assert result.confidence == 1.0

    def test_non_list_fields_become_empty_tuples(self):
        result = _result_from_tool_input(
            {"passed": True, "confidence": 0.5, "issues_found": "oops", "remediation_steps": 5}
        )
        assert result.issues_found == ()
        assert result.recommendations == ()
        assert result.remediation_steps == ()


# ---------------------------------------------------------------------------
# run_verification_agent tests
# ---------------------------------------------------------------------------


def _default_run_kwargs() -> dict:
    """Common kwargs for run_verification_agent."""
    return {
        "original_quality_flags": {"col_a": {"flag": "missing_values"}},
        "steps_applied": [
            {"operation": "fill_null", "column": "col_a", "description": "Fill nulls"}
        ],
        "audit_log_sample": [{"row": 1, "column": "col_a", "original_value": None, "new_value": 0}],
        "cleaned_sample_rows": [{"id": 1, "name": "Alice", "score": 100, "col_a": 0}],
        "deterministic_report": {
            "overall_passed": True,
            "flags_resolved": ["col_a"],
            "flags_remaining": [],
            "audit_completeness": 0.95,
            "summary": "All checks passed",
        },
    }


class TestRunVerificationAgent:
    @patch("app.services.verification_agent._get_client")
    @patch("app.services.verification_agent._SYSTEM_PROMPT_PATH")
    def test_run_verification_agent_success(self, mock_path, mock_get_client):
        mock_path.read_text.return_value = "You are a verification agent."
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(_valid_agent_json())
        mock_get_client.return_value = mock_client

        result = run_verification_agent(**_default_run_kwargs())

        assert result.passed is True
        assert result.confidence == 0.95
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        # Assert against config, not a literal — the model tier is env-driven,
        # so pinning the string here just breaks on every model bump.
        assert call_kwargs["model"] == settings.VERIFICATION_MODEL
        assert call_kwargs["max_tokens"] == 8192
        # The submit_verification tool is forced.
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_verification"}
        assert call_kwargs["tools"][0]["name"] == "submit_verification"

    @patch("app.services.verification_agent._get_client")
    @patch("app.services.verification_agent._SYSTEM_PROMPT_PATH")
    def test_run_verification_agent_includes_remediation_steps(self, mock_path, mock_get_client):
        mock_path.read_text.return_value = "You are a verification agent."
        payload = _valid_agent_json(
            passed=False,
            confidence=0.6,
            remediation_steps=[
                {
                    "operation": "cap_extreme_values",
                    "column": "HotelExpense",
                    "params": {"max_value": 50000},
                    "description": "Step R1: Cap hotel expense",
                },
            ],
            issues_found=[
                {
                    "column": "HotelExpense",
                    "issue": "Extreme outlier",
                    "severity": "CRITICAL",
                    "detail": "1B value",
                },
            ],
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(payload)
        mock_get_client.return_value = mock_client

        result = run_verification_agent(**_default_run_kwargs())

        assert result.passed is False
        assert len(result.remediation_steps) == 1
        assert result.remediation_steps[0]["operation"] == "cap_extreme_values"
        assert len(result.issues_found) == 1
        assert result.issues_found[0]["severity"] == "CRITICAL"

    @patch("app.services.verification_agent._get_client")
    @patch("app.services.verification_agent._SYSTEM_PROMPT_PATH")
    def test_run_verification_agent_no_tool_call_returns_failed(self, mock_path, mock_get_client):
        mock_path.read_text.return_value = "You are a verification agent."
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_only_response()
        mock_get_client.return_value = mock_client

        result = run_verification_agent(**_default_run_kwargs())

        assert result.passed is False
        assert result.confidence == 0.0
        assert len(result.issues_found) == 1
        assert result.issues_found[0]["severity"] == "HIGH"
        assert "no structured result" in result.issues_found[0]["issue"].lower()

    @patch("app.services.structured_output.time.sleep")
    @patch("app.services.verification_agent._get_client")
    @patch("app.services.verification_agent._SYSTEM_PROMPT_PATH")
    def test_run_verification_agent_rate_limit_retry(self, mock_path, mock_get_client, mock_sleep):
        from anthropic import RateLimitError

        mock_path.read_text.return_value = "You are a verification agent."

        # Build a minimal mock httpx.Response for the RateLimitError
        mock_http_response = MagicMock()
        mock_http_response.status_code = 429
        mock_http_response.headers = {"retry-after": "1"}
        type(mock_http_response).text = PropertyMock(return_value='{"error": "rate_limited"}')

        rate_limit_exc = RateLimitError(
            message="Rate limited",
            response=mock_http_response,
            body={"error": {"message": "Rate limited", "type": "rate_limit_error"}},
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            rate_limit_exc,
            _make_mock_response(_valid_agent_json()),
        ]
        mock_get_client.return_value = mock_client

        result = run_verification_agent(**_default_run_kwargs())

        assert result.passed is True
        assert mock_client.messages.create.call_count == 2
        mock_sleep.assert_called_once_with(15.0)

    @patch("app.services.verification_agent._get_client")
    @patch("app.services.verification_agent._SYSTEM_PROMPT_PATH")
    def test_payload_trimming(self, mock_path, mock_get_client):
        mock_path.read_text.return_value = "You are a verification agent."
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(_valid_agent_json())
        mock_get_client.return_value = mock_client

        # Create large sample rows with many columns
        large_row = {f"col_{i}": f"value_{i}" for i in range(100)}
        large_row.update({"id": 1, "name": "Alice", "score": 100})
        large_rows = [dict(large_row, id=i) for i in range(50)]

        # Only a few columns are flagged
        quality_flags = {"col_5": {"flag": "outlier"}, "col_10": {"flag": "missing"}}

        kwargs = _default_run_kwargs()
        kwargs["cleaned_sample_rows"] = large_rows
        kwargs["original_quality_flags"] = quality_flags

        run_verification_agent(**kwargs)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]

        # The user message should NOT contain all 100 columns — only flagged + context cols
        assert "col_50" not in user_msg
        assert "col_99" not in user_msg
        # Flagged columns should be present
        assert "col_5" in user_msg
        assert "col_10" in user_msg
        # Should trim to max 20 rows
        assert user_msg.count('"id":') <= 20
