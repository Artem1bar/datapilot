"""Unit tests for the pure-logic helpers in app/services/manipulation.py.

We cover everything that does not require a live Anthropic API or R2 storage:
  - _dataframe_to_bytes()     — serialization round-trips for each format
  - generate_preview()        — meta-logic over execute_operations()
  - parse_manipulation_intent() — AI parsing, with the client mocked out
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.manipulation import (
    _dataframe_to_bytes,
    generate_preview,
    parse_manipulation_intent,
)
from app.services.manipulation_executor import ManipulationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _df(data: dict[str, list]) -> pd.DataFrame:
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# _dataframe_to_bytes
# ---------------------------------------------------------------------------


class TestDataframeToBytes:
    def test_csv_round_trip(self):
        df = _df({"a": [1, 2], "b": ["x", "y"]})
        raw = _dataframe_to_bytes(df, "data.csv")
        result = pd.read_csv(io.BytesIO(raw))
        assert list(result.columns) == ["a", "b"]
        assert list(result["a"]) == [1, 2]

    def test_tsv_round_trip(self):
        df = _df({"col1": [10], "col2": ["hello"]})
        raw = _dataframe_to_bytes(df, "export.tsv")
        result = pd.read_csv(io.BytesIO(raw), sep="\t")
        assert list(result.columns) == ["col1", "col2"]
        assert result["col2"].iloc[0] == "hello"

    def test_json_round_trip(self):
        df = _df({"x": [1, 2, 3]})
        raw = _dataframe_to_bytes(df, "records.json")
        result = pd.read_json(io.BytesIO(raw))
        assert list(result["x"]) == [1, 2, 3]

    def test_excel_round_trip(self):
        df = _df({"name": ["Alice", "Bob"], "score": [90, 85]})
        raw = _dataframe_to_bytes(df, "report.xlsx")
        result = pd.read_excel(io.BytesIO(raw))
        assert list(result.columns) == ["name", "score"]
        assert list(result["name"]) == ["Alice", "Bob"]

    def test_xls_extension_treated_as_excel(self):
        df = _df({"val": [42]})
        raw = _dataframe_to_bytes(df, "legacy.xls")
        result = pd.read_excel(io.BytesIO(raw))
        assert result["val"].iloc[0] == 42

    def test_unknown_extension_falls_back_to_csv(self):
        df = _df({"k": ["v"]})
        raw = _dataframe_to_bytes(df, "mystery.dat")
        result = pd.read_csv(io.BytesIO(raw))
        assert result["k"].iloc[0] == "v"

    def test_parquet_round_trip(self):
        df = _df({"n": [100, 200]})
        raw = _dataframe_to_bytes(df, "big.parquet")
        result = pd.read_parquet(io.BytesIO(raw))
        assert list(result["n"]) == [100, 200]


# ---------------------------------------------------------------------------
# generate_preview
# ---------------------------------------------------------------------------


class TestGeneratePreview:
    def test_no_ops_returns_unchanged_preview(self):
        df = _df({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result = generate_preview(df, [])
        assert result["preview_before"] == result["preview_after"]
        assert result["affected_row_count"] == 0
        assert result["warnings"] == []
        assert result["confirmation_required"] is False

    def test_column_deletion_adds_warning(self):
        df = _df({"keep": [1, 2], "drop_me": [3, 4]})
        ops: list[dict[str, Any]] = [
            {"op_type": "delete_columns", "params": {"columns": ["drop_me"]}, "description": "drop"}
        ]
        result = generate_preview(df, ops)
        assert any("drop_me" in w for w in result["warnings"])
        assert "drop_me" not in [c for c in result["preview_after"][0].keys()]

    def test_column_deletion_sets_confirmation_required(self):
        df = _df({"a": [1], "b": [2]})
        ops = [{"op_type": "delete_columns", "params": {"columns": ["b"]}, "description": "drop b"}]
        result = generate_preview(df, ops)
        assert result["confirmation_required"] is True

    def test_large_row_removal_adds_warning_and_requires_confirmation(self):
        # Filter keeps only 1 of 20 rows (95% removal > 10% threshold)
        df = _df({"score": list(range(20))})
        ops = [
            {
                "op_type": "filter_rows",
                "params": {"column": "score", "operator": "==", "value": 0},
                "description": "keep score 0 only",
            }
        ]
        result = generate_preview(df, ops)
        assert any("row" in w.lower() for w in result["warnings"])
        assert result["confirmation_required"] is True
        assert result["affected_row_count"] == 19

    def test_minor_row_removal_no_confirmation(self):
        # Keep rows where v != 0: removes 1 of 100 rows (1% < 10% threshold) — no confirmation
        df = _df({"v": list(range(100))})
        ops = [
            {
                "op_type": "filter_rows",
                "params": {"column": "v", "operator": "!=", "value": 0},
                "description": "drop zero",
            }
        ]
        result = generate_preview(df, ops)
        assert result["confirmation_required"] is False

    def test_before_after_sample_capped_at_five_rows(self):
        df = _df({"x": list(range(50))})
        result = generate_preview(df, [])
        assert len(result["preview_before"]) == 5
        assert len(result["preview_after"]) == 5

    def test_affected_columns_includes_renamed_column(self):
        df = _df({"old": [1, 2], "other": [3, 4]})
        ops = [
            {
                "op_type": "rename_column",
                "params": {"old_name": "old", "new_name": "new"},
                "description": "rename",
            }
        ]
        result = generate_preview(df, ops)
        affected = result["affected_columns"]
        # "old" disappears, "new" appears — symmetric difference
        assert "old" in affected or "new" in affected

    def test_operations_echoed_in_result(self):
        df = _df({"a": [1]})
        ops = [
            {
                "op_type": "sort",
                "params": {"column": "a", "ascending": True},
                "description": "sort a",
            }
        ]
        result = generate_preview(df, ops)
        assert result["operations"] is ops

    def test_execute_error_propagates(self):
        df = _df({"a": [1]})
        ops = [
            {
                "op_type": "delete_columns",
                "params": {"columns": ["nonexistent"]},
                "description": "bad",
            }
        ]
        with pytest.raises(ManipulationError):
            generate_preview(df, ops)


# ---------------------------------------------------------------------------
# parse_manipulation_intent  (Anthropic client mocked)
# ---------------------------------------------------------------------------


def _mock_response(json_text: str) -> MagicMock:
    block = MagicMock()
    block.text = json_text
    response = MagicMock()
    response.content = [block]
    return response


class TestParseManipulationIntent:
    def _call(self, command: str, json_text: str) -> list[dict[str, Any]]:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json_text)
        with patch("app.services.manipulation._get_client", return_value=mock_client):
            return parse_manipulation_intent(
                command=command,
                column_names=["name", "score"],
                dtypes={"name": "object", "score": "int64"},
                sample_rows=[{"name": "Alice", "score": 90}],
            )

    def test_returns_parsed_list(self):
        ops = [
            {
                "op_type": "sort",
                "params": {"column": "score", "ascending": False},
                "description": "sort desc",
            }
        ]
        result = self._call("sort by score descending", json.dumps(ops))
        assert result == ops

    def test_strips_markdown_fences(self):
        ops = [
            {
                "op_type": "sort",
                "params": {"column": "score", "ascending": True},
                "description": "sort asc",
            }
        ]
        fenced = f"```json\n{json.dumps(ops)}\n```"
        result = self._call("sort ascending", fenced)
        assert result == ops

    def test_raises_on_invalid_json(self):
        from app.services.manipulation_executor import ManipulationError

        with pytest.raises(ManipulationError, match="Failed to parse"):
            self._call("do something", "not json at all")

    def test_raises_when_response_is_not_list(self):
        from app.services.manipulation_executor import ManipulationError

        with pytest.raises(ManipulationError, match="non-list"):
            self._call("do something", '{"key": "value"}')

    def test_raises_when_no_text_block(self):
        from app.services.manipulation_executor import ManipulationError

        mock_client = MagicMock()
        response = MagicMock()
        response.content = []  # no text blocks
        mock_client.messages.create.return_value = response
        with patch("app.services.manipulation._get_client", return_value=mock_client):
            with pytest.raises(ManipulationError, match="No text content"):
                parse_manipulation_intent("cmd", ["col"], {"col": "int"}, [])
