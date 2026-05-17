"""Unit tests for pure helper functions in the analysis service."""

from __future__ import annotations

import json

from app.services.analysis import _build_dataset_context, _extract_json


class TestExtractJson:
    def test_plain_json_object(self):
        text = '{"answer": "hello", "charts": []}'
        result = _extract_json(text)
        assert result is not None
        assert result["answer"] == "hello"

    def test_json_in_code_fence(self):
        text = '```json\n{"answer": "hi", "charts": []}\n```'
        result = _extract_json(text)
        assert result is not None
        assert result["answer"] == "hi"

    def test_json_in_unnamed_code_fence(self):
        text = '```\n{"answer": "yo"}\n```'
        result = _extract_json(text)
        assert result is not None
        assert result["answer"] == "yo"

    def test_json_embedded_in_prose(self):
        text = 'Sure, here you go: {"answer": "found it", "charts": []} Hope that helps!'
        result = _extract_json(text)
        assert result is not None
        assert result["answer"] == "found it"

    def test_returns_none_for_plain_prose(self):
        text = "This is just regular text with no JSON at all."
        result = _extract_json(text)
        assert result is None

    def test_returns_none_for_malformed_json(self):
        text = '{"broken": true, missing_quote: "oops"}'
        result = _extract_json(text)
        assert result is None

    def test_nested_object(self):
        data = {"answer": "ok", "charts": [{"type": "bar", "data": [1, 2]}]}
        result = _extract_json(json.dumps(data))
        assert result is not None
        assert result["charts"][0]["type"] == "bar"

    def test_empty_object(self):
        result = _extract_json("{}")
        assert result == {}

    def test_code_fence_with_trailing_text(self):
        text = "Analysis:\n```json\n{\"answer\": \"yes\"}\n```\nEnd."
        result = _extract_json(text)
        assert result is not None
        assert result["answer"] == "yes"


class TestBuildDatasetContext:
    def test_contains_profile(self):
        profile = {"row_count": 5, "columns": []}
        rows = [{"a": 1}]
        ctx = _build_dataset_context(profile, rows)
        assert "Dataset Profile" in ctx
        assert '"row_count": 5' in ctx

    def test_contains_sample_rows(self):
        profile = {}
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        ctx = _build_dataset_context(profile, rows)
        assert "Sample Rows" in ctx
        assert "Alice" in ctx
        assert "Bob" in ctx

    def test_sections_in_order(self):
        profile = {"a": 1}
        rows = [{"x": 2}]
        ctx = _build_dataset_context(profile, rows)
        profile_pos = ctx.index("Dataset Profile")
        sample_pos = ctx.index("Sample Rows")
        assert profile_pos < sample_pos

    def test_empty_profile_and_rows(self):
        ctx = _build_dataset_context({}, [])
        assert "Dataset Profile" in ctx
        assert "Sample Rows" in ctx

    def test_non_serializable_values_handled(self):
        import datetime
        profile = {"created": datetime.date(2024, 1, 1)}
        rows = []
        ctx = _build_dataset_context(profile, rows)
        assert "2024-01-01" in ctx
