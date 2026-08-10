"""Unit tests for pure helper functions in the analysis service and router."""

from __future__ import annotations

import io
import json

import pandas as pd

from app.routers.analysis import _read_sample_rows
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
        text = 'Analysis:\n```json\n{"answer": "yes"}\n```\nEnd.'
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


# ---------------------------------------------------------------------------
# _read_sample_rows  (router utility, no I/O — reads from bytes)
# ---------------------------------------------------------------------------


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


class TestReadSampleRows:
    def test_csv_returns_list_of_dicts(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        rows = _read_sample_rows(_csv_bytes(df), "data.csv")
        assert isinstance(rows, list)
        assert rows[0]["a"] == 1
        assert rows[0]["b"] == "x"

    def test_csv_capped_at_n_rows(self):
        df = pd.DataFrame({"v": range(50)})
        rows = _read_sample_rows(_csv_bytes(df), "big.csv", n=10)
        assert len(rows) == 10

    def test_excel_round_trip(self):
        df = pd.DataFrame({"name": ["Alice", "Bob"], "score": [90, 85]})
        rows = _read_sample_rows(_excel_bytes(df), "report.xlsx")
        assert rows[0]["name"] == "Alice"
        assert rows[1]["score"] == 85

    def test_xls_extension_treated_as_excel(self):
        df = pd.DataFrame({"val": [42]})
        rows = _read_sample_rows(_excel_bytes(df), "legacy.xls")
        assert rows[0]["val"] == 42

    def test_parquet_round_trip(self):
        df = pd.DataFrame({"x": [10, 20, 30]})
        rows = _read_sample_rows(_parquet_bytes(df), "data.parquet", n=2)
        assert len(rows) == 2
        assert rows[0]["x"] == 10

    def test_unknown_extension_falls_back_to_csv(self):
        df = pd.DataFrame({"k": ["hello"]})
        rows = _read_sample_rows(_csv_bytes(df), "mystery.txt")
        assert rows[0]["k"] == "hello"

    def test_empty_dataframe_returns_empty_list(self):
        df = pd.DataFrame({"col": pd.Series([], dtype="object")})
        rows = _read_sample_rows(_csv_bytes(df), "empty.csv")
        assert rows == []
