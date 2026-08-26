"""Unit tests for pure helper functions in the analysis service and router."""

from __future__ import annotations

import io
import json

import pandas as pd

from app.routers.analysis import _load_analysis_frame
from app.services.analysis import _build_planner_context, _extract_json


class TestExtractJson:
    def test_plain_json_object(self):
        result = _extract_json('{"answer": "yes"}')
        assert result is not None
        assert result["answer"] == "yes"

    def test_json_in_code_fence(self):
        result = _extract_json('```json\n{"answer": "yes"}\n```')
        assert result is not None
        assert result["answer"] == "yes"

    def test_json_in_unnamed_code_fence(self):
        result = _extract_json('```\n{"answer": "yes"}\n```')
        assert result is not None
        assert result["answer"] == "yes"

    def test_json_embedded_in_prose(self):
        result = _extract_json('Here is the spec:\n{"answer": "yes"}\nDone.')
        assert result is not None
        assert result["answer"] == "yes"

    def test_returns_none_for_plain_prose(self):
        assert _extract_json("I cannot answer that question.") is None

    def test_returns_none_for_malformed_json(self):
        assert _extract_json('{"answer": ') is None

    def test_returns_none_for_json_array(self):
        # A spec must be an object; a bare array is not one.
        assert _extract_json("[1, 2, 3]") is None

    def test_nested_object(self):
        result = _extract_json('{"a": {"b": {"c": 1}}}')
        assert result is not None
        assert result["a"]["b"]["c"] == 1

    def test_empty_object(self):
        assert _extract_json("{}") == {}

    def test_code_fence_with_trailing_text(self):
        text = 'Analysis:\n```json\n{"answer": "yes"}\n```\nEnd.'
        result = _extract_json(text)
        assert result is not None
        assert result["answer"] == "yes"


class TestBuildPlannerContext:
    """The planner sees real dtypes, the profile, and a small labelled sample."""

    def _frame(self) -> pd.DataFrame:
        return pd.DataFrame({"region": ["West", "East"], "revenue": [10.5, 20.0]})

    def test_reports_real_dtypes(self):
        ctx = _build_planner_context({}, self._frame())
        # dtypes come from the frame, because that is what the validator checks.
        assert "Column dtypes" in ctx
        assert "float64" in ctx

    def test_contains_profile(self):
        ctx = _build_planner_context({"row_count": 5}, self._frame())
        assert '"row_count": 5' in ctx

    def test_reports_row_and_column_counts(self):
        ctx = _build_planner_context({}, self._frame())
        assert "2 rows" in ctx
        assert "2 columns" in ctx

    def test_sample_is_labelled_as_non_evidence(self):
        # The planner must not draw conclusions from the sample, so the header
        # says so explicitly.
        ctx = _build_planner_context({}, self._frame())
        assert "not evidence" in ctx

    def test_sample_is_capped(self):
        df = pd.DataFrame({"n": range(500)})
        ctx = _build_planner_context({}, df)
        # 10-row sample cap: row 400 must not appear in the sample section.
        assert ctx.count("400") == 0

    def test_non_serializable_values_handled(self):
        import datetime

        ctx = _build_planner_context({"created": datetime.date(2024, 1, 1)}, self._frame())
        assert "2024-01-01" in ctx

    def test_empty_profile(self):
        ctx = _build_planner_context({}, self._frame())
        assert "Profile" in ctx


# ---------------------------------------------------------------------------
# _load_analysis_frame  (router utility, no I/O — reads from bytes)
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


class TestLoadAnalysisFrame:
    def test_csv_returns_every_row(self):
        # Analysis executes over the full dataset — no sampling at load time.
        df = pd.DataFrame({"a": range(500)})
        loaded = _load_analysis_frame(_csv_bytes(df), "data.csv")
        assert len(loaded) == 500

    def test_excel_round_trip(self):
        df = pd.DataFrame({"x": [1, 2], "y": ["a", "b"]})
        loaded = _load_analysis_frame(_excel_bytes(df), "data.xlsx")
        assert list(loaded.columns) == ["x", "y"]
        assert len(loaded) == 2

    def test_parquet_round_trip(self):
        df = pd.DataFrame({"n": [1, 2, 3]})
        loaded = _load_analysis_frame(_parquet_bytes(df), "data.parquet")
        assert len(loaded) == 3

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": []})
        loaded = _load_analysis_frame(_csv_bytes(df), "data.csv")
        assert len(loaded) == 0

    def test_date_named_column_is_parsed_to_datetime(self):
        # CSV carries no dtype metadata, so without this the resample operation
        # would be unreachable on every CSV upload.
        df = pd.DataFrame({"order_date": ["2024-01-01", "2024-02-01"], "n": [1, 2]})
        loaded = _load_analysis_frame(_csv_bytes(df), "data.csv")
        assert pd.api.types.is_datetime64_any_dtype(loaded["order_date"])

    def test_date_named_column_of_free_text_stays_text(self):
        # A date-like name over unparseable values must not become NaT columns.
        df = pd.DataFrame({"date_notes": ["ask the vendor", "unknown", "n/a"]})
        loaded = _load_analysis_frame(_csv_bytes(df), "data.csv")
        assert not pd.api.types.is_datetime64_any_dtype(loaded["date_notes"])

    def test_non_date_named_column_is_left_alone(self):
        df = pd.DataFrame({"label": ["2024-01-01", "2024-02-01"]})
        loaded = _load_analysis_frame(_csv_bytes(df), "data.csv")
        assert not pd.api.types.is_datetime64_any_dtype(loaded["label"])


def test_planner_context_dtype_block_parses():
    """The dtype block must be valid JSON — the planner relies on it verbatim."""
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    ctx = _build_planner_context({"row_count": 2}, df)

    start = ctx.index("{", ctx.index("Column dtypes"))
    end = ctx.index("}", start)
    dtypes = json.loads(ctx[start : end + 1])

    assert set(dtypes) == {"a", "b"}
    assert "int" in dtypes["a"]
