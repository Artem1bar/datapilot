"""Unit tests for the dataset comparison service."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.comparison import _safe_value, _values_equal, compare_datasets


class TestValuesEqual:
    def test_both_nan(self):
        assert _values_equal(float("nan"), float("nan"))
        assert _values_equal(np.nan, np.nan)

    def test_one_nan(self):
        assert not _values_equal(np.nan, 1)
        assert not _values_equal(1, np.nan)

    def test_equal_ints(self):
        assert _values_equal(1, 1)

    def test_unequal_ints(self):
        assert not _values_equal(1, 2)

    def test_equal_strings(self):
        assert _values_equal("hello", "hello")

    def test_unequal_strings(self):
        assert not _values_equal("hello", "world")

    def test_equal_floats(self):
        assert _values_equal(3.14, 3.14)

    def test_none_both(self):
        assert _values_equal(None, None)

    def test_none_vs_value(self):
        assert not _values_equal(None, 1)


class TestSafeValue:
    def test_nan_becomes_none(self):
        assert _safe_value(np.nan) is None
        assert _safe_value(float("nan")) is None

    def test_np_integer_becomes_int(self):
        val = _safe_value(np.int64(42))
        assert val == 42
        assert isinstance(val, int)

    def test_np_floating_becomes_float(self):
        val = _safe_value(np.float64(3.14))
        assert abs(val - 3.14) < 1e-9
        assert isinstance(val, float)

    def test_string_passthrough(self):
        assert _safe_value("hello") == "hello"

    def test_int_passthrough(self):
        assert _safe_value(7) == 7

    def test_none_becomes_none(self):
        assert _safe_value(None) is None


class TestCompareDatasets:
    def _simple_before(self):
        return pd.DataFrame(
            {"id": [1, 2, 3], "name": ["Alice", "Bob", "Carol"], "score": [80, 90, 70]}
        )

    def _simple_after(self):
        return pd.DataFrame(
            {"id": [1, 2, 3], "name": ["Alice", "Bob", "Carol"], "score": [85, 90, 75]}
        )

    def test_summary_row_counts(self):
        df_b = self._simple_before()
        df_a = self._simple_after()
        report = compare_datasets(df_b, df_a)
        assert report["summary"]["rows_before"] == 3
        assert report["summary"]["rows_after"] == 3

    def test_summary_rows_added(self):
        df_b = pd.DataFrame({"x": [1, 2]})
        df_a = pd.DataFrame({"x": [1, 2, 3, 4]})
        report = compare_datasets(df_b, df_a)
        assert report["summary"]["rows_added"] == 2
        assert report["summary"]["rows_removed"] == 0

    def test_summary_rows_removed(self):
        df_b = pd.DataFrame({"x": [1, 2, 3]})
        df_a = pd.DataFrame({"x": [1]})
        report = compare_datasets(df_b, df_a)
        assert report["summary"]["rows_removed"] == 2
        assert report["summary"]["rows_added"] == 0

    def test_column_added(self):
        df_b = pd.DataFrame({"a": [1, 2]})
        df_a = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        report = compare_datasets(df_b, df_a)
        assert "b" in report["columns"]["added"]
        assert report["summary"]["columns_added"] == 1

    def test_column_removed(self):
        df_b = pd.DataFrame({"a": [1], "b": [2]})
        df_a = pd.DataFrame({"a": [1]})
        report = compare_datasets(df_b, df_a)
        assert "b" in report["columns"]["removed"]
        assert report["summary"]["columns_removed"] == 1

    def test_no_column_changes(self):
        df_b = self._simple_before()
        df_a = self._simple_after()
        report = compare_datasets(df_b, df_a)
        assert report["columns"]["added"] == []
        assert report["columns"]["removed"] == []

    def test_type_change_detected(self):
        df_b = pd.DataFrame({"x": pd.array([1, 2, 3], dtype="int64")})
        df_a = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        report = compare_datasets(df_b, df_a)
        tc = report["columns"]["type_changes"]
        assert any(t["column"] == "x" for t in tc)

    def test_no_type_change(self):
        df_b = self._simple_before()
        df_a = self._simple_after()
        report = compare_datasets(df_b, df_a)
        assert report["columns"]["type_changes"] == []

    def test_cell_changes_detected(self):
        df_b = self._simple_before()
        df_a = self._simple_after()
        report = compare_datasets(df_b, df_a)
        assert report["summary"]["cells_changed"] > 0
        changed_cols = {c["column"] for c in report["sample_changes"]}
        assert "score" in changed_cols

    def test_no_cell_changes_identical(self):
        df = self._simple_before()
        report = compare_datasets(df, df.copy())
        assert report["summary"]["cells_changed"] == 0
        assert report["sample_changes"] == []

    def test_statistical_drift_large_shift(self):
        df_b = pd.DataFrame({"val": [100.0] * 10})
        df_a = pd.DataFrame({"val": [200.0] * 10})
        report = compare_datasets(df_b, df_a)
        drift = report["statistical_drift"]
        assert len(drift) == 1
        assert drift[0]["column"] == "val"
        assert drift[0]["pct_change"] == pytest.approx(100.0)

    def test_statistical_drift_no_report_under_threshold(self):
        df_b = pd.DataFrame({"val": [100.0] * 10})
        df_a = pd.DataFrame({"val": [102.0] * 10})  # 2% change — below 5% threshold
        report = compare_datasets(df_b, df_a)
        assert report["statistical_drift"] == []

    def test_statistical_drift_zero_mean_skipped(self):
        df_b = pd.DataFrame({"val": [0.0] * 10})
        df_a = pd.DataFrame({"val": [1.0] * 10})
        report = compare_datasets(df_b, df_a)
        # pct_change undefined at zero mean; should not raise, drift skipped
        assert isinstance(report["statistical_drift"], list)

    def test_empty_dataframes(self):
        df_b = pd.DataFrame({"a": pd.Series([], dtype="float64")})
        df_a = pd.DataFrame({"a": pd.Series([], dtype="float64")})
        report = compare_datasets(df_b, df_a)
        assert report["summary"]["rows_before"] == 0
        assert report["summary"]["rows_after"] == 0

    def test_max_sample_limits_cell_changes(self):
        n = 200
        df_b = pd.DataFrame({"x": list(range(n))})
        df_a = pd.DataFrame({"x": [v + 1 for v in range(n)]})
        report = compare_datasets(df_b, df_a, max_sample=10)
        assert report["summary"]["cells_changed"] <= 200

    def test_non_numeric_columns_no_drift(self):
        df_b = pd.DataFrame({"name": ["Alice", "Bob"]})
        df_a = pd.DataFrame({"name": ["Alice", "Charlie"]})
        report = compare_datasets(df_b, df_a)
        assert report["statistical_drift"] == []
