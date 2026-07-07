"""Tests for generate_cleaning_plan's validate-and-regenerate loop (Claude mocked)."""

from __future__ import annotations

import json
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


def _response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _plan(*steps: dict) -> str:
    return json.dumps({"steps": list(steps), "summary": "s", "estimated_row_impact": None})


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
        retry_messages = client.messages.create.call_args_list[1].kwargs["messages"]
        assert retry_messages[1]["role"] == "assistant"
        assert "hallucinated_op" in retry_messages[2]["content"]

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

    def test_unparseable_response_regenerates(self, mock_get_client, _prompt):
        client = MagicMock()
        client.messages.create.side_effect = [
            _response("Sure, here is what I would do (no JSON at all)."),
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
