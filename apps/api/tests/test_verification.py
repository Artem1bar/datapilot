"""Unit tests for the deterministic verification service.

Tests verify_cleaning_result with known dirty/clean DataFrames
to ensure the verification logic correctly identifies pass/fail states.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.verification import (
    VerificationReport,
    verify_cleaning_result,
    _validate_remove_currency_symbols,
    _validate_free_to_zero,
    _validate_extract_number,
    _validate_convert_number_words,
    _validate_remove_vague_entries,
    _validate_strip_whitespace,
    _validate_deduplicate,
    _compute_audit_completeness,
)


# ---------------------------------------------------------------------------
# Per-operation validator tests
# ---------------------------------------------------------------------------

class TestValidateRemoveCurrencySymbols:
    def test_passes_when_clean(self):
        df = pd.DataFrame({"cost": ["100", "200", "300"]})
        result = _validate_remove_currency_symbols(df, "cost", {})
        assert result.passed == True

    def test_fails_when_currency_remains(self):
        df = pd.DataFrame({"cost": ["$100", "200", "$300"]})
        result = _validate_remove_currency_symbols(df, "cost", {})
        assert result.passed == False
        assert len(result.remaining_issues) == 2

    def test_passes_for_missing_column(self):
        df = pd.DataFrame({"other": [1, 2]})
        result = _validate_remove_currency_symbols(df, "cost", {})
        assert result.passed == True


class TestValidateFreeToZero:
    def test_passes_when_no_free(self):
        df = pd.DataFrame({"cost": [0, 100, 200]})
        result = _validate_free_to_zero(df, "cost", {})
        assert result.passed == True

    def test_fails_when_free_remains(self):
        df = pd.DataFrame({"cost": ["Free", 100, "free (comp)"]})
        result = _validate_free_to_zero(df, "cost", {})
        assert result.passed == False
        assert len(result.remaining_issues) == 2


class TestValidateExtractNumber:
    def test_passes_when_numeric(self):
        df = pd.DataFrame({"val": [1.5, 2.0, 3.5]})
        result = _validate_extract_number(df, "val", {})
        assert result.passed == True

    def test_fails_when_mostly_text(self):
        df = pd.DataFrame({"val": ["abc", "def", "ghi", 1.0]})
        result = _validate_extract_number(df, "val", {})
        assert result.passed == False


class TestValidateConvertNumberWords:
    def test_passes_when_no_words(self):
        df = pd.DataFrame({"count": [1, 5, 20]})
        result = _validate_convert_number_words(df, "count", {})
        assert result.passed == True

    def test_fails_when_words_remain(self):
        df = pd.DataFrame({"count": ["one", "two", 3]})
        result = _validate_convert_number_words(df, "count", {})
        assert result.passed == False


class TestValidateRemoveVagueEntries:
    def test_passes_when_no_vague(self):
        df = pd.DataFrame({"val": ["100", "200", "300"]})
        result = _validate_remove_vague_entries(df, "val", {})
        assert result.passed == True

    def test_fails_when_vague_remains(self):
        df = pd.DataFrame({"val": ["n/a", "100", "none"]})
        result = _validate_remove_vague_entries(df, "val", {})
        assert result.passed == False


class TestValidateStripWhitespace:
    def test_passes_when_clean(self):
        df = pd.DataFrame({"name": ["alice", "bob"]})
        result = _validate_strip_whitespace(df, "name", {})
        assert result.passed == True

    def test_fails_when_whitespace_remains(self):
        df = pd.DataFrame({"name": ["  alice  ", "bob"]})
        result = _validate_strip_whitespace(df, "name", {})
        assert result.passed == False


class TestValidateDeduplicate:
    def test_passes_when_no_duplicates(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = _validate_deduplicate(df, None, {})
        assert result.passed == True

    def test_fails_when_duplicates_remain(self):
        df = pd.DataFrame({"a": [1, 1, 2]})
        result = _validate_deduplicate(df, None, {})
        assert result.passed == False


# ---------------------------------------------------------------------------
# Audit completeness
# ---------------------------------------------------------------------------

class TestAuditCompleteness:
    def test_full_coverage(self):
        original = pd.DataFrame({"Expense_Lodging": ["$100", "$200", "300"]})
        flags = {"Expense_Lodging": {"has_currency": True}}
        audit_log = [
            {"column": "Expense_Lodging", "row": 1, "operation": "remove_currency_symbols"},
            {"column": "Expense_Lodging", "row": 2, "operation": "remove_currency_symbols"},
        ]
        completeness = _compute_audit_completeness(original, flags, audit_log)
        assert completeness == 1.0

    def test_zero_coverage(self):
        original = pd.DataFrame({"Expense_Lodging": ["$100", "$200"]})
        flags = {"Expense_Lodging": {"has_currency": True}}
        audit_log = []
        completeness = _compute_audit_completeness(original, flags, audit_log)
        assert completeness == 0.0

    def test_no_flags_returns_1(self):
        original = pd.DataFrame({"a": [1, 2, 3]})
        completeness = _compute_audit_completeness(original, {}, [])
        assert completeness == 1.0


# ---------------------------------------------------------------------------
# Full verification pipeline
# ---------------------------------------------------------------------------

class TestVerifyCleaningResult:
    def test_all_passed_clean_data(self):
        """Cleaning fully resolved all quality flags."""
        original = pd.DataFrame({"cost": ["$100", "Free", "n/a", "50"]})
        cleaned = pd.DataFrame({"cost": [100.0, 0.0, None, 50.0]})

        steps = [
            {"operation": "free_to_zero", "column": "cost", "params": {}},
            {"operation": "remove_currency_symbols", "column": "cost", "params": {}},
            {"operation": "remove_vague_entries", "column": "cost", "params": {}},
        ]

        audit_log = [
            {"row": 1, "column": "cost", "original_value": "$100", "new_value": 100.0, "operation": "remove_currency_symbols"},
            {"row": 2, "column": "cost", "original_value": "Free", "new_value": 0, "operation": "free_to_zero"},
            {"row": 3, "column": "cost", "original_value": "n/a", "new_value": None, "operation": "remove_vague_entries"},
        ]

        # The original flags for "cost" column
        original_flags = {
            "cost": {"has_currency": True, "has_free_values": True, "has_vague_values": True}
        }

        report = verify_cleaning_result(
            original_df=original,
            cleaned_df=cleaned,
            steps=steps,
            audit_log=audit_log,
            original_quality_flags=original_flags,
        )

        assert isinstance(report, VerificationReport)
        # Steps should pass their postconditions
        for step_result in report.step_results:
            if step_result.operation in ("free_to_zero", "remove_currency_symbols", "remove_vague_entries"):
                assert step_result.passed == True, f"{step_result.operation} should pass"

    def test_failed_step_included(self):
        """Steps that failed during execution are reported."""
        original = pd.DataFrame({"cost": ["$100", "$200"]})
        cleaned = pd.DataFrame({"cost": ["$100", "$200"]})  # unchanged

        steps = [
            {"operation": "remove_currency_symbols", "column": "cost", "params": {}},
        ]

        failed_steps = [
            {"step_index": 0, "operation": "remove_currency_symbols", "column": "cost", "error": "test error"},
        ]

        report = verify_cleaning_result(
            original_df=original,
            cleaned_df=cleaned,
            steps=steps,
            audit_log=[],
            original_quality_flags={"cost": {"has_currency": True}},
            failed_steps=failed_steps,
        )

        assert report.overall_passed == False
        assert len(report.failed_steps) == 1
        assert report.step_results[0].passed is False
