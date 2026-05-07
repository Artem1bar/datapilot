"""Tests for the generate_data_dictionary service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

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


def _make_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=content)]
    return resp


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_returns_valid_dictionary_json() -> None:
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _make_response(
            json.dumps(VALID_RESPONSE)
        )
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert "dataset_summary" in result
    assert "columns" in result
    assert len(result["columns"]) == 3
    assert result["columns"][0]["name"] == "customer_id"


def test_strips_markdown_code_fences() -> None:
    fenced = f"```json\n{json.dumps(VALID_RESPONSE)}\n```"
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _make_response(fenced)
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert result["dataset_summary"] == VALID_RESPONSE["dataset_summary"]


def test_prompt_includes_column_names() -> None:
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        instance = mock_cls.return_value
        instance.messages.create.return_value = _make_response(json.dumps(VALID_RESPONSE))
        generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    call_kwargs = instance.messages.create.call_args
    user_content = call_kwargs.kwargs["messages"][0]["content"]
    assert "customer_id" in user_content
    assert "score" in user_content


def test_uses_haiku_model() -> None:
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        instance = mock_cls.return_value
        instance.messages.create.return_value = _make_response(json.dumps(VALID_RESPONSE))
        generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    model_used = instance.messages.create.call_args.kwargs["model"]
    assert "haiku" in model_used


# ---------------------------------------------------------------------------
# Error / fallback paths
# ---------------------------------------------------------------------------


def test_returns_fallback_on_anthropic_error() -> None:
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = RuntimeError("API down")
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert result["dataset_summary"] == "Failed to generate data dictionary"
    assert result["columns"] == []


def test_returns_fallback_on_invalid_json() -> None:
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _make_response("not json {{{")
        result = generate_data_dictionary(PROFILE, SAMPLE_ROWS)

    assert result["columns"] == []


def test_empty_profile_does_not_raise() -> None:
    with patch("app.services.data_dictionary.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _make_response(
            json.dumps({"dataset_summary": "empty", "columns": []})
        )
        result = generate_data_dictionary({}, [])

    assert result["columns"] == []
