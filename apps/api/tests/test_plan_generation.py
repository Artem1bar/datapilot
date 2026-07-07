"""Tests for generate_cleaning_plan's validate-and-regenerate loop (Claude mocked).

Plan generation forces a submit_cleaning_plan tool call, so the mocked responses
carry a tool_use block whose ``.input`` is the plan dict.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.cleaning import generate_cleaning_plan

PROFILE = {"columns": {"amount": {}, "name": {}}}
SAMPLES = [{"amount": "$5", "name": "a"}]

GOOD_STEP = {
    "operation": "strip_whitespace",
    "column": "name",
    "params": {},
    "description": "Step 1: strip",
}
BAD_OP_STEP = {
    "operation": "hallucinated_op",
    "column": "name",
    "params": {},
    "description": "Step 1: nonsense",
}


def _plan(*steps: dict) -> dict:
    return {"steps": list(steps), "summary": "s"}


def _response(plan: dict, *, tool_id: str = "toolu_plan") -> MagicMock:
    """Build a mock response whose content is a submit_cleaning_plan tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_cleaning_plan"
    block.id = tool_id
    block.input = plan
    response = MagicMock()
    response.content = [block]
    return response


@patch("app.services.cleaning._load_system_prompt", return_value="system prompt")
@patch("app.services.cleaning._get_client")
class TestGenerateCleaningPlan:
    def test_valid_plan_first_attempt_single_call(self, mock_get_client, _prompt):
        client = MagicMock()
        client.messages.create.side_effect = [_response(_plan(GOOD_STEP))]
        mock_get_client.return_value = client

        steps = generate_cleaning_plan(PROFILE, SAMPLES)

        assert client.messages.create.call_count == 1
        assert steps[0]["operation"] == "strip_whitespace"
        # The submit_cleaning_plan tool is forced.
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_cleaning_plan"}

    def test_invalid_operation_regenerates_with_feedback(self, mock_get_client, _prompt):
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(_plan(BAD_OP_STEP)),
            _response(_plan(GOOD_STEP)),
        ]
        mock_get_client.return_value = client

        steps = generate_cleaning_plan(PROFILE, SAMPLES)

        assert client.messages.create.call_count == 2
        assert steps[0]["operation"] == "strip_whitespace"
        # The regenerate turn feeds the validator error back as a tool_result.
        retry_messages = client.messages.create.call_args_list[1].kwargs["messages"]
        assert retry_messages[1]["role"] == "assistant"
        tool_result = retry_messages[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert "hallucinated_op" in tool_result["content"]

    def test_unknown_column_regenerates(self, mock_get_client, _prompt):
        bad_col = {
            "operation": "strip_whitespace",
            "column": "ghost",
            "params": {},
            "description": "",
        }
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(_plan(bad_col)),
            _response(_plan(GOOD_STEP)),
        ]
        mock_get_client.return_value = client

        steps = generate_cleaning_plan(PROFILE, SAMPLES)

        assert client.messages.create.call_count == 2
        assert len(steps) == 1

    def test_malformed_steps_regenerates(self, mock_get_client, _prompt):
        # First call returns steps that are not an array of objects → rejected.
        client = MagicMock()
        client.messages.create.side_effect = [
            _response({"steps": "not a list", "summary": "s"}),
            _response(_plan(GOOD_STEP)),
        ]
        mock_get_client.return_value = client

        steps = generate_cleaning_plan(PROFILE, SAMPLES)

        assert client.messages.create.call_count == 2
        assert len(steps) == 1

    def test_raises_after_two_invalid_attempts(self, mock_get_client, _prompt):
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(_plan(BAD_OP_STEP)),
            _response(_plan(BAD_OP_STEP)),
        ]
        mock_get_client.return_value = client

        with pytest.raises(ValueError, match="after 2 attempts"):
            generate_cleaning_plan(PROFILE, SAMPLES)

        assert client.messages.create.call_count == 2

    def test_rationale_and_confidence_flow_through(self, mock_get_client, _prompt):
        step = {
            "operation": "strip_whitespace",
            "column": "name",
            "params": {},
            "description": "Step 1: strip",
            "rationale": "trailing spaces present",
            "confidence": 0.8,
        }
        client = MagicMock()
        client.messages.create.side_effect = [_response(_plan(step))]
        mock_get_client.return_value = client

        steps = generate_cleaning_plan(PROFILE, SAMPLES)

        assert steps[0]["rationale"] == "trailing spaces present"
        assert steps[0]["confidence"] == 0.8

    def test_missing_confidence_becomes_none(self, mock_get_client, _prompt):
        client = MagicMock()
        client.messages.create.side_effect = [_response(_plan(GOOD_STEP))]
        mock_get_client.return_value = client

        steps = generate_cleaning_plan(PROFILE, SAMPLES)

        assert steps[0]["confidence"] is None
        assert steps[0]["rationale"] == ""
