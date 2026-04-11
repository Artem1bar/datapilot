"""Unit tests for all cleaning operations in app/services/cleaning.py.

Each test creates a small DataFrame, applies one operation, and asserts
the output is correct and the audit log captures the changes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.cleaning import execute_cleaning_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_step(df: pd.DataFrame, operation: str, column: str | None = None, **params):
    """Execute a single cleaning step and return (cleaned_df, audit_log, failed_steps)."""
    steps = [{"operation": operation, "column": column, "params": params, "description": "test"}]
    return execute_cleaning_plan(df, steps)


# ---------------------------------------------------------------------------
# drop_rows
# ---------------------------------------------------------------------------

class TestDropRows:
    def test_drops_specified_rows(self):
        df = pd.DataFrame({"a": ["header_text", "1", "2", "3"]})
        cleaned, audit, failed = _run_step(df, "drop_rows", indices=[0])
        assert len(cleaned) == 3
        assert cleaned["a"].tolist() == ["1", "2", "3"]
        assert len(failed) == 0

    def test_empty_indices_no_change(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        cleaned, audit, failed = _run_step(df, "drop_rows", indices=[])
        assert len(cleaned) == 3


# ---------------------------------------------------------------------------
# strip_whitespace
# ---------------------------------------------------------------------------

class TestStripWhitespace:
    def test_strips_leading_trailing(self):
        df = pd.DataFrame({"name": ["  alice  ", "bob  ", "  carol"]})
        cleaned, audit, failed = _run_step(df, "strip_whitespace", "name")
        assert cleaned["name"].tolist() == ["alice", "bob", "carol"]
        assert len(audit) == 3
        assert len(failed) == 0

    def test_no_change_on_clean_data(self):
        df = pd.DataFrame({"name": ["alice", "bob"]})
        cleaned, audit, failed = _run_step(df, "strip_whitespace", "name")
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# remove_currency_symbols
# ---------------------------------------------------------------------------

class TestRemoveCurrencySymbols:
    def test_removes_dollar_sign(self):
        df = pd.DataFrame({"cost": ["$100", "$50.00", "200"]})
        cleaned, audit, failed = _run_step(df, "remove_currency_symbols", "cost")
        assert cleaned["cost"].tolist() == ["100", "50.00", "200"]
        assert len(failed) == 0

    def test_removes_euro_and_pound(self):
        df = pd.DataFrame({"cost": ["€100", "£50"]})
        cleaned, audit, failed = _run_step(df, "remove_currency_symbols", "cost")
        assert cleaned["cost"].tolist() == ["100", "50"]

    def test_missing_column_skips(self):
        df = pd.DataFrame({"other": [1, 2]})
        cleaned, audit, failed = _run_step(df, "remove_currency_symbols", "nonexistent")
        assert len(audit) == 0
        assert len(failed) == 0


# ---------------------------------------------------------------------------
# extract_number
# ---------------------------------------------------------------------------

class TestExtractNumber:
    def test_extracts_from_text(self):
        df = pd.DataFrame({"val": ["$400 a person", "1.5 hours", "pure text"]})
        cleaned, audit, failed = _run_step(df, "extract_number", "val")
        assert cleaned["val"].iloc[0] == 400
        assert cleaned["val"].iloc[1] == 1.5
        assert cleaned["val"].iloc[2] == "pure text"  # no number found

    def test_handles_commas(self):
        df = pd.DataFrame({"val": ["1,500", "2,000,000"]})
        cleaned, audit, failed = _run_step(df, "extract_number", "val")
        assert cleaned["val"].iloc[0] == 1500
        assert cleaned["val"].iloc[1] == 2000000


# ---------------------------------------------------------------------------
# convert_number_words
# ---------------------------------------------------------------------------

class TestConvertNumberWords:
    def test_converts_basic_words(self):
        df = pd.DataFrame({"count": ["one", "five", "twenty"]})
        cleaned, audit, failed = _run_step(df, "convert_number_words", "count")
        assert cleaned["count"].tolist() == [1, 5, 20]

    def test_leaves_non_number_words(self):
        df = pd.DataFrame({"count": ["hello", "world"]})
        cleaned, audit, failed = _run_step(df, "convert_number_words", "count")
        assert cleaned["count"].tolist() == ["hello", "world"]
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# free_to_zero
# ---------------------------------------------------------------------------

class TestFreeToZero:
    def test_converts_free_variations(self):
        df = pd.DataFrame({"cost": ["Free", "free", "Free (comp)", "$100"]})
        cleaned, audit, failed = _run_step(df, "free_to_zero", "cost")
        assert cleaned["cost"].iloc[0] == 0
        assert cleaned["cost"].iloc[1] == 0
        assert cleaned["cost"].iloc[2] == 0
        assert cleaned["cost"].iloc[3] == "$100"

    def test_preserves_non_free(self):
        df = pd.DataFrame({"cost": ["100", "200"]})
        cleaned, audit, failed = _run_step(df, "free_to_zero", "cost")
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# remove_vague_entries
# ---------------------------------------------------------------------------

class TestRemoveVagueEntries:
    def test_removes_known_vague_words(self):
        df = pd.DataFrame({"amount": ["n/a", "none", "unknown", "100"]})
        cleaned, audit, failed = _run_step(df, "remove_vague_entries", "amount")
        assert pd.isna(cleaned["amount"].iloc[0])
        assert pd.isna(cleaned["amount"].iloc[1])
        assert pd.isna(cleaned["amount"].iloc[2])
        assert cleaned["amount"].iloc[3] == "100"

    def test_preserves_valid_values(self):
        df = pd.DataFrame({"amount": ["100", "200", "300"]})
        cleaned, audit, failed = _run_step(df, "remove_vague_entries", "amount")
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# cast_type
# ---------------------------------------------------------------------------

class TestCastType:
    def test_cast_to_float(self):
        df = pd.DataFrame({"val": ["1.5", "2.0", "3.5"]})
        cleaned, audit, failed = _run_step(df, "cast_type", "val", target_type="float")
        assert cleaned["val"].dtype in (float, "float64")

    def test_cast_to_int(self):
        df = pd.DataFrame({"val": ["1", "2", "3"]})
        cleaned, audit, failed = _run_step(df, "cast_type", "val", target_type="int")
        assert cleaned["val"].dtype in (int, "int64", "Int64")


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def test_removes_full_duplicates(self):
        df = pd.DataFrame({"a": [1, 1, 2, 2, 3], "b": ["x", "x", "y", "y", "z"]})
        cleaned, audit, failed = _run_step(df, "deduplicate")
        assert len(cleaned) == 3


# ---------------------------------------------------------------------------
# execute_cleaning_plan — error handling
# ---------------------------------------------------------------------------

class TestExecuteCleaningPlan:
    def test_unknown_operation_recorded_as_failed(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        steps = [{"operation": "nonexistent_op", "column": "a", "params": {}, "description": "bad"}]
        cleaned, audit, failed = execute_cleaning_plan(df, steps)
        assert len(failed) == 1
        assert failed[0]["operation"] == "nonexistent_op"
        assert "Unknown" in failed[0]["error"]

    def test_multiple_steps_execute_in_order(self):
        df = pd.DataFrame({"cost": ["  $100  ", "  Free  "]})
        steps = [
            {"operation": "strip_whitespace", "column": "cost", "params": {}, "description": "trim"},
            {"operation": "free_to_zero", "column": "cost", "params": {}, "description": "free→0"},
            {"operation": "remove_currency_symbols", "column": "cost", "params": {}, "description": "strip $"},
        ]
        cleaned, audit, failed = execute_cleaning_plan(df, steps)
        assert len(failed) == 0
        assert str(cleaned["cost"].iloc[0]) == "100"
        # free_to_zero sets to 0 (int), then remove_currency_symbols converts to str "0"
        assert str(cleaned["cost"].iloc[1]) == "0"
