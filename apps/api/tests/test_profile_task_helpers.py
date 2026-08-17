"""Tests for pure helper functions in profile_task.py.

These functions have no external dependencies — no DB, no storage, no Celery —
so they run fast without any mocking.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from app.tasks.profile_task import (
    _compute_profile,
    _to_python,
    detect_quality_issues,
    generate_smart_suggestions,
)

# ---------------------------------------------------------------------------
# _to_python — numpy/pandas → plain Python
# ---------------------------------------------------------------------------


class TestToPython:
    def test_numpy_integer(self) -> None:
        assert _to_python(np.int64(42)) == 42
        assert isinstance(_to_python(np.int64(42)), int)

    def test_numpy_floating(self) -> None:
        result = _to_python(np.float64(3.14))
        assert abs(result - 3.14) < 1e-10
        assert isinstance(result, float)

    def test_numpy_bool(self) -> None:
        assert _to_python(np.bool_(True)) is True
        assert isinstance(_to_python(np.bool_(True)), bool)

    def test_numpy_array(self) -> None:
        arr = np.array([1, 2, 3])
        assert _to_python(arr) == [1, 2, 3]

    def test_datetime_object(self) -> None:
        dt = datetime(2026, 1, 15, 12, 0, 0)
        assert _to_python(dt) == dt.isoformat()

    def test_date_object(self) -> None:
        d = date(2026, 6, 1)
        assert _to_python(d) == d.isoformat()

    def test_nested_dict(self) -> None:
        data = {"count": np.int64(5), "score": np.float64(0.9)}
        result = _to_python(data)
        assert result == {"count": 5, "score": 0.9}
        assert isinstance(result["count"], int)

    def test_nested_list(self) -> None:
        data = [np.int64(1), np.float64(2.5), "plain"]
        result = _to_python(data)
        assert result == [1, 2.5, "plain"]

    def test_plain_python_passthrough(self) -> None:
        for val in [42, 3.14, "hello", True, None]:
            assert _to_python(val) == val

    def test_empty_dict(self) -> None:
        assert _to_python({}) == {}

    def test_empty_list(self) -> None:
        assert _to_python([]) == []


# ---------------------------------------------------------------------------
# _compute_profile — DataFrame statistics
# ---------------------------------------------------------------------------


class TestComputeProfile:
    def _simple_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "age": [25, 30, 35, 40, None],
                "name": ["Alice", "Bob", "Charlie", "Dave", None],
                "score": [1.0, 2.5, 3.0, 4.5, 5.0],
            }
        )

    def test_row_and_col_counts(self) -> None:
        df = self._simple_df()
        profile = _compute_profile(df)
        assert profile["row_count"] == 5
        assert profile["col_count"] == 3

    def test_numeric_column_stats(self) -> None:
        df = self._simple_df()
        profile = _compute_profile(df)
        age_stats = profile["columns"]["age"]
        assert age_stats["null_count"] == 1
        assert age_stats["null_pct"] == 20.0
        assert "mean" in age_stats
        assert "min" in age_stats
        assert "max" in age_stats
        assert "median" in age_stats

    def test_percentiles_present(self) -> None:
        df = pd.DataFrame({"x": list(range(100))})
        profile = _compute_profile(df)
        col = profile["columns"]["x"]
        assert "p95" in col
        assert "p99" in col
        assert "mad" in col

    def test_string_column_stats(self) -> None:
        df = self._simple_df()
        profile = _compute_profile(df)
        name_stats = profile["columns"]["name"]
        assert "top_values" in name_stats
        assert "avg_length" in name_stats
        assert "max_length" in name_stats
        assert name_stats["null_count"] == 1

    def test_all_values_json_serializable(self) -> None:
        import json

        df = pd.DataFrame(
            {
                "int_col": [1, 2, 3],
                "float_col": [1.1, 2.2, 3.3],
                "str_col": ["a", "b", "c"],
            }
        )
        profile = _compute_profile(df)
        # Should not raise — all values are plain Python types
        json.dumps(profile)

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame({"a": [], "b": []})
        profile = _compute_profile(df)
        assert profile["row_count"] == 0
        assert profile["col_count"] == 2

    def test_suggestions_key_present(self) -> None:
        df = self._simple_df()
        profile = _compute_profile(df)
        assert "suggestions" in profile

    def test_quality_flags_attached_when_issues_exist(self) -> None:
        df = pd.DataFrame(
            {
                "empty_col": [None, None, None],
                "normal": [1, 2, 3],
            }
        )
        profile = _compute_profile(df)
        assert "data_quality" in profile
        assert "_empty_columns" in profile["data_quality"]

    def test_no_quality_key_when_no_issues(self) -> None:
        df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
        profile = _compute_profile(df)
        assert "data_quality" not in profile


# ---------------------------------------------------------------------------
# generate_smart_suggestions
# ---------------------------------------------------------------------------


class TestGenerateSmartSuggestions:
    def _profile_for(self, df: pd.DataFrame) -> dict:
        return _compute_profile(df)

    def test_drop_candidate_for_all_null_column(self) -> None:
        df = pd.DataFrame({"good": [1, 2, 3], "empty": [None, None, None]})
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        drop_cols = [s["column"] for s in suggestions["drop_candidates"]]
        assert "empty" in drop_cols

    def test_drop_candidate_for_constant_column(self) -> None:
        df = pd.DataFrame({"x": [1, 2, 3], "const": ["same", "same", "same"]})
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        drop_cols = [s["column"] for s in suggestions["drop_candidates"]]
        assert "const" in drop_cols

    def test_type_conversion_numeric_string(self) -> None:
        df = pd.DataFrame({"price": ["10.5", "20.0", "30.1", "40.2", "50.3"] * 3})
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        type_cols = [s["column"] for s in suggestions["type_conversions"]]
        assert "price" in type_cols

    def test_type_conversion_date_string(self) -> None:
        df = pd.DataFrame({"date_col": ["2026-01-01", "2026-01-02", "2026-01-03"] * 5})
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        type_cols = [s["column"] for s in suggestions["type_conversions"]]
        assert "date_col" in type_cols

    def test_pii_detection_email_column(self) -> None:
        emails = [f"user{i}@example.com" for i in range(30)]
        df = pd.DataFrame({"email_addr": emails})
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        pii_cols = [s["column"] for s in suggestions["pii_detected"]]
        assert "email_addr" in pii_cols

    def test_clean_dataframe_no_drop_candidates(self) -> None:
        df = pd.DataFrame(
            {
                "a": [1, 2, 3, 4, 5],
                "b": ["x", "y", "z", "w", "v"],
            }
        )
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        assert suggestions["drop_candidates"] == []

    def test_suggestions_structure_keys(self) -> None:
        df = pd.DataFrame({"x": [1, 2, 3]})
        profile = self._profile_for(df)
        suggestions = generate_smart_suggestions(df, profile)
        assert set(suggestions.keys()) == {
            "drop_candidates",
            "type_conversions",
            "standardization",
            "pii_detected",
        }


# ---------------------------------------------------------------------------
# detect_quality_issues — additional edge cases
# ---------------------------------------------------------------------------


class TestDetectQualityIssuesEdgeCases:
    def test_dirty_column_names_flag(self) -> None:
        df = pd.DataFrame({" col with spaces ": [1, 2], "good": [3, 4]})
        flags = detect_quality_issues(df)
        assert "_dirty_column_names" in flags
        assert " col with spaces " in flags["_dirty_column_names"]["columns"]

    def test_empty_column_flag(self) -> None:
        df = pd.DataFrame({"all_null": [None, None, None], "ok": [1, 2, 3]})
        flags = detect_quality_issues(df)
        assert "_empty_columns" in flags
        assert "all_null" in flags["_empty_columns"]["columns"]

    def test_number_word_flag(self) -> None:
        df = pd.DataFrame({"count": ["one", "two", "three", "four", 5]})
        flags = detect_quality_issues(df)
        assert "count" in flags
        assert flags["count"]["has_number_words"] is True

    def test_no_flags_for_clean_data(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        flags = detect_quality_issues(df)
        assert flags == {}

    def test_extreme_outlier_flag(self) -> None:
        values = [10.0] * 20 + [100_000.0]
        df = pd.DataFrame({"cost": values})
        flags = detect_quality_issues(df, domain="survey")
        if "cost" in flags:
            assert flags["cost"].get("has_extreme_outliers") is True
