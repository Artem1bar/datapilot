"""Tests for the generate_data_dictionary service.

The service forces a ``submit_data_dictionary`` tool call (via
``structured_output.request_tool_call``) so the SDK returns an already-parsed
dict — scraping JSON from free text broke when the model appended prose after
the object. These tests mock a tool_use response accordingly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import app.services.data_dictionary as dict_mod
from app.services.data_dictionary import generate_data_dictionary

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PROFILE = {
    "row_count": 100,
    "col_count": 3,
    "columns": {
        "customer_id": {"dtype": "int64", "null_pct": 0.0, "unique_count": 100},
        "name": {
            "dtype": "object",
            "null_pct": 0.02,
            "unique_count": 98,
            "top_values": {"Alice": 3, "Bob": 2},
        },
        "score": {
            "dtype": "float64",
            "null_pct": 0.0,
            "unique_count": 80,
            "mean": 75.3,
            "min": 10.0,
            "max": 100.0,
        },
    },
}

SAMPLE_ROWS = [
    {"customer_id": 1, "name": "Alice", "score": 92.5},
    {"customer_id": 2, "name": "Bob", "score": 78.0},
]

VALID_RESPONSE = {
    "dataset_summary": "Customer scoring dataset with 100 rows and 3 columns.",
    "columns": [
        {
            "name": "customer_id",
            "description": "Unique customer identifier.",
            "business_meaning": "Primary key.",
            "data_type": "integer",
            "constraints": ["not null", "unique"],
            "notes": "",
        },
        {
            "name": "name",
            "description": "Customer full name.",
            "business_meaning": "Display name.",
            "data_type": "string",
            "constraints": [],
            "notes": "Contains PII",
        },
        {
            "name": "score",
            "description": "Customer engagement score.",
            "business_meaning": "Used for segmentation.",
            "data_type": "float",
            "constraints": ["range: 0-100"],
            "notes": "",
        },
    ],
}


def _make_response(payload: dict) -> MagicMock:
    """A mock Anthropic Message carrying a submit_data_dictionary tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_data_dictionary"
    block.id = "toolu_dict"
    block.input = payload
    resp = MagicMock()
    resp.content = [block]
    return resp


def _mock_client(response: MagicMock | None = None, error: Exception | None = None) -> MagicMock:
    """Return a mock Anthropic client whose messages.create returns response or raises error."""
    client = MagicMock()
    if error is not None:
        client.messages.create.side_effect = error
    else:
        client.messages.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_returns_valid_dictionary() -> None:
    client = _mock_client(_make_response(VALID_RESPONSE))
    with patch.object(dict_mod, "_get_client", return_value=client):
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert "dataset_summary" in result
    assert "columns" in result
    assert len(result["columns"]) == 3
    assert result["columns"][0]["name"] == "customer_id"


def test_forces_the_dictionary_tool() -> None:
    # Structured output via forced tool use — no free-text JSON parsing.
    client = _mock_client(_make_response(VALID_RESPONSE))
    with patch.object(dict_mod, "_get_client", return_value=client):
        generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_data_dictionary"}
    assert kwargs["tools"][0]["name"] == "submit_data_dictionary"


def test_prompt_includes_column_names() -> None:
    client = _mock_client(_make_response(VALID_RESPONSE))
    with patch.object(dict_mod, "_get_client", return_value=client):
        generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "customer_id" in user_content
    assert "score" in user_content


def test_uses_haiku_model() -> None:
    client = _mock_client(_make_response(VALID_RESPONSE))
    with patch.object(dict_mod, "_get_client", return_value=client):
        generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    model_used = client.messages.create.call_args.kwargs["model"]
    assert "haiku" in model_used


# ---------------------------------------------------------------------------
# Error / fallback paths
# ---------------------------------------------------------------------------


def test_returns_fallback_on_anthropic_error() -> None:
    client = _mock_client(error=RuntimeError("API down"))
    with patch.object(dict_mod, "_get_client", return_value=client):
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert result["dataset_summary"] == "Failed to generate data dictionary"
    assert result["columns"] == []


def test_returns_fallback_when_model_skips_tool() -> None:
    # A response with no tool_use block makes request_tool_call raise -> fallback.
    text_block = MagicMock()
    text_block.type = "text"
    resp = MagicMock()
    resp.content = [text_block]
    client = _mock_client(resp)
    with patch.object(dict_mod, "_get_client", return_value=client):
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert result["columns"] == []


def test_empty_profile_does_not_raise() -> None:
    client = _mock_client(_make_response({"dataset_summary": "empty", "columns": []}))
    with patch.object(dict_mod, "_get_client", return_value=client):
        result = generate_data_dictionary({}, [])

    assert result["columns"] == []
