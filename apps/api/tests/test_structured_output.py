"""Tests for the forced-tool-use structured output helper."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from anthropic import RateLimitError

from app.services.structured_output import ToolCallResult, coerce_confidence, request_tool_call

TOOL = {
    "name": "submit_thing",
    "description": "Submit a thing.",
    "input_schema": {"type": "object", "properties": {}},
}


def _tool_use_response(
    payload: dict, *, tool_name: str = "submit_thing", tool_id: str = "toolu_1"
) -> MagicMock:
    """Build a mock response whose content is a single tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.id = tool_id
    block.input = payload
    response = MagicMock()
    response.content = [block]
    return response


def _text_only_response(text: str = "no tool here") -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _rate_limit_error() -> RateLimitError:
    http_response = MagicMock()
    http_response.status_code = 429
    http_response.headers = {"retry-after": "1"}
    type(http_response).text = PropertyMock(return_value='{"error": "rate_limited"}')
    return RateLimitError(
        message="Rate limited",
        response=http_response,
        body={"error": {"message": "Rate limited", "type": "rate_limit_error"}},
    )


def _call(client: MagicMock, **overrides) -> ToolCallResult:
    kwargs = {
        "model": "claude-opus-4-8",
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "tool": TOOL,
        "max_tokens": 1024,
    }
    kwargs.update(overrides)
    return request_tool_call(client, **kwargs)


class TestRequestToolCall:
    def test_returns_parsed_tool_input(self):
        client = MagicMock()
        client.messages.create.return_value = _tool_use_response({"a": 1, "b": [2, 3]})

        result = _call(client)

        assert isinstance(result, ToolCallResult)
        assert result.input == {"a": 1, "b": [2, 3]}
        assert result.tool_use_id == "toolu_1"

    def test_forces_tool_choice_and_passes_tool(self):
        client = MagicMock()
        client.messages.create.return_value = _tool_use_response({})

        _call(client)

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_thing"}
        assert kwargs["tools"] == [TOOL]
        assert kwargs["model"] == "claude-opus-4-8"
        assert kwargs["max_tokens"] == 1024

    def test_input_is_copied_not_aliased(self):
        client = MagicMock()
        payload = {"a": 1}
        client.messages.create.return_value = _tool_use_response(payload)

        result = _call(client)
        result.input["a"] = 99

        assert payload["a"] == 1  # mutating the result must not touch the source

    def test_raises_when_no_tool_use_block(self):
        client = MagicMock()
        client.messages.create.return_value = _text_only_response()

        with pytest.raises(ValueError, match="did not call the required tool"):
            _call(client)

    @patch("app.services.structured_output.time.sleep")
    def test_retries_on_rate_limit_then_succeeds(self, mock_sleep):
        client = MagicMock()
        client.messages.create.side_effect = [
            _rate_limit_error(),
            _tool_use_response({"ok": True}),
        ]

        result = _call(client, rate_limit_wait=15)

        assert result.input == {"ok": True}
        assert client.messages.create.call_count == 2
        mock_sleep.assert_called_once_with(15)

    @patch("app.services.structured_output.time.sleep")
    def test_reraises_after_rate_limit_exhausted(self, mock_sleep):
        client = MagicMock()
        client.messages.create.side_effect = [_rate_limit_error(), _rate_limit_error()]

        with pytest.raises(RateLimitError):
            _call(client, rate_limit_retries=2)

        assert client.messages.create.call_count == 2


class TestCoerceConfidence:
    def test_fraction_passthrough(self):
        assert coerce_confidence(0.75) == 0.75

    def test_percentage_normalized(self):
        assert coerce_confidence(90) == 0.9

    def test_clamped_to_unit_range(self):
        assert coerce_confidence(150) == 1.0  # 150% normalizes then clamps to 1.0
        assert coerce_confidence(-1) == 0.0

    def test_non_numeric_returns_none(self):
        assert coerce_confidence(None) is None
        assert coerce_confidence("high") is None

    def test_non_finite_returns_none(self):
        assert coerce_confidence(float("nan")) is None
        assert coerce_confidence(float("inf")) is None
