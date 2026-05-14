"""Unit tests for manipulation_executor.py pure DataFrame operations.

All functions are pure (no I/O), so tests run without a database or network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.manipulation_executor import (
    ManipulationError,
    execute_add_column,
    execute_cast_type,
    execute_delete_columns,
    execute_drop_duplicates,
    execute_fill_nulls,
    execute_filter_rows,
    execute_format_column,
    execute_merge_columns,
    execute_move_column,
    execute_operations,
    execute_rename_column,
    execute_reorder_columns,
    execute_sort,
    execute_split_column,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": ["Alice", "Bob", "Carol", "Bob"],
            "age": [30, 25, 35, 25],
            "score": [88.5, 92.0, 75.0, 92.0],
            "city": ["NY", "LA", None, "LA"],
        }
    )


# ── execute_delete_columns ────────────────────────────────────────────────────


class TestDeleteColumns:
    def test_drops_single_column(self, sample_df: pd.DataFrame) -> None:
        result = execute_delete_columns(sample_df, {"columns": ["city"]})
        assert "city" not in result.columns
        assert len(result.columns) == 3

    def test_drops_multiple_columns(self, sample_df: pd.DataFrame) -> None:
        result = execute_delete_columns(sample_df, {"columns": ["age", "score"]})
        assert "age" not in result.columns
        assert "score" not in result.columns
        assert "name" in result.columns

    def test_no_columns_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="No columns"):
            execute_delete_columns(sample_df, {"columns": []})

    def test_missing_column_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="not found"):
            execute_delete_columns(sample_df, {"columns": ["nonexistent"]})

    def test_does_not_mutate_input(self, sample_df: pd.DataFrame) -> None:
        original_cols = list(sample_df.columns)
        execute_delete_columns(sample_df, {"columns": ["age"]})
        assert list(sample_df.columns) == original_cols


# ── execute_rename_column ─────────────────────────────────────────────────────


class TestRenameColumn:
    def test_renames_column(self, sample_df: pd.DataFrame) -> None:
        result = execute_rename_column(sample_df, {"old_name": "name", "new_name": "full_name"})
        assert "full_name" in result.columns
        assert "name" not in result.columns

    def test_missing_old_name_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError):
            execute_rename_column(sample_df, {"old_name": "nonexistent", "new_name": "x"})

    def test_new_name_conflict_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="already exists"):
            execute_rename_column(sample_df, {"old_name": "name", "new_name": "age"})

    def test_empty_names_raise(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError):
            execute_rename_column(sample_df, {"old_name": "", "new_name": "x"})


# ── execute_sort ──────────────────────────────────────────────────────────────


class TestSort:
    def test_sort_ascending(self, sample_df: pd.DataFrame) -> None:
        result = execute_sort(sample_df, {"column": "age", "ascending": True})
        ages = list(result["age"])
        assert ages == sorted(ages)

    def test_sort_descending(self, sample_df: pd.DataFrame) -> None:
        result = execute_sort(sample_df, {"column": "score", "ascending": False})
        scores = list(result["score"])
        assert scores == sorted(scores, reverse=True)

    def test_missing_column_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError):
            execute_sort(sample_df, {"column": "nonexistent"})

    def test_no_column_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="required"):
            execute_sort(sample_df, {})


# ── execute_filter_rows ───────────────────────────────────────────────────────


class TestFilterRows:
    def test_greater_than(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "age", "operator": ">", "value": 28})
        assert all(result["age"] > 28)

    def test_equals(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "name", "operator": "==", "value": "Bob"})
        assert all(result["name"] == "Bob")

    def test_not_equals(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "name", "operator": "!=", "value": "Bob"})
        assert "Bob" not in result["name"].values

    def test_contains(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "name", "operator": "contains", "value": "li"})
        assert all("li" in n.lower() for n in result["name"])

    def test_not_contains(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "name", "operator": "not_contains", "value": "Bob"})
        assert "Bob" not in result["name"].values

    def test_is_null(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "city", "operator": "is_null", "value": None})
        assert result["city"].isna().all()

    def test_is_not_null(self, sample_df: pd.DataFrame) -> None:
        result = execute_filter_rows(sample_df, {"column": "city", "operator": "is_not_null", "value": None})
        assert not result["city"].isna().any()

    def test_unknown_operator_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="Unknown operator"):
            execute_filter_rows(sample_df, {"column": "age", "operator": "between", "value": 30})

    def test_missing_column_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError):
            execute_filter_rows(sample_df, {"column": "salary", "operator": ">", "value": 50000})


# ── execute_add_column ────────────────────────────────────────────────────────


class TestAddColumn:
    def test_add_with_default_value(self, sample_df: pd.DataFrame) -> None:
        result = execute_add_column(sample_df, {"name": "status", "default_value": "active"})
        assert "status" in result.columns
        assert (result["status"] == "active").all()

    def test_add_with_source_columns_sum(self, sample_df: pd.DataFrame) -> None:
        result = execute_add_column(
            sample_df,
            {"name": "age_score", "source_columns": ["age", "score"], "operation": "sum"},
        )
        assert "age_score" in result.columns
        assert result["age_score"].iloc[0] == pytest.approx(30 + 88.5)

    def test_add_with_source_columns_concat(self, sample_df: pd.DataFrame) -> None:
        result = execute_add_column(
            sample_df,
            {"name": "label", "source_columns": ["name", "city"], "operation": "concat", "separator": "-"},
        )
        assert result["label"].iloc[0] == "Alice-NY"

    def test_conflict_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="already exists"):
            execute_add_column(sample_df, {"name": "age", "default_value": 0})

    def test_no_name_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="required"):
            execute_add_column(sample_df, {"name": "", "default_value": 0})


# ── execute_merge_columns ─────────────────────────────────────────────────────


class TestMergeColumns:
    def test_merges_with_separator(self, sample_df: pd.DataFrame) -> None:
        result = execute_merge_columns(
            sample_df, {"columns": ["name", "city"], "separator": ", ", "new_name": "location"}
        )
        assert result["location"].iloc[0] == "Alice, NY"

    def test_drops_originals(self, sample_df: pd.DataFrame) -> None:
        result = execute_merge_columns(
            sample_df,
            {"columns": ["name", "city"], "separator": "_", "new_name": "nc", "drop_originals": True},
        )
        assert "name" not in result.columns
        assert "city" not in result.columns

    def test_fewer_than_two_columns_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="At least 2"):
            execute_merge_columns(sample_df, {"columns": ["name"], "separator": "_", "new_name": "x"})

    def test_no_new_name_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="required"):
            execute_merge_columns(sample_df, {"columns": ["name", "city"], "separator": "_", "new_name": ""})


# ── execute_format_column ─────────────────────────────────────────────────────


class TestFormatColumn:
    def test_uppercase(self, sample_df: pd.DataFrame) -> None:
        result = execute_format_column(sample_df, {"column": "name", "format_type": "uppercase"})
        assert result["name"].iloc[0] == "ALICE"

    def test_lowercase(self, sample_df: pd.DataFrame) -> None:
        result = execute_format_column(sample_df, {"column": "name", "format_type": "lowercase"})
        assert result["name"].iloc[0] == "alice"

    def test_titlecase(self, sample_df: pd.DataFrame) -> None:
        df = pd.DataFrame({"city": ["new york", "los angeles"]})
        result = execute_format_column(df, {"column": "city", "format_type": "titlecase"})
        assert result["city"].iloc[0] == "New York"

    def test_currency(self, sample_df: pd.DataFrame) -> None:
        result = execute_format_column(sample_df, {"column": "score", "format_type": "currency"})
        assert result["score"].iloc[0] == "$88.50"

    def test_percentage(self, sample_df: pd.DataFrame) -> None:
        df = pd.DataFrame({"rate": [0.85, 0.92]})
        result = execute_format_column(df, {"column": "rate", "format_type": "percentage"})
        assert result["rate"].iloc[0] == "0.8%"

    def test_integer(self, sample_df: pd.DataFrame) -> None:
        result = execute_format_column(sample_df, {"column": "score", "format_type": "integer"})
        assert result["score"].iloc[0] == "88"

    def test_trim(self) -> None:
        df = pd.DataFrame({"text": ["  hello  ", " world "]})
        result = execute_format_column(df, {"column": "text", "format_type": "trim"})
        assert result["text"].iloc[0] == "hello"

    def test_unknown_format_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="Unknown format_type"):
            execute_format_column(sample_df, {"column": "name", "format_type": "base64"})


# ── execute_move_column ───────────────────────────────────────────────────────


class TestMoveColumn:
    def test_move_before(self, sample_df: pd.DataFrame) -> None:
        result = execute_move_column(sample_df, {"column": "score", "before": "name"})
        assert list(result.columns)[0] == "score"

    def test_move_after(self, sample_df: pd.DataFrame) -> None:
        result = execute_move_column(sample_df, {"column": "city", "after": "name"})
        cols = list(result.columns)
        assert cols.index("city") == cols.index("name") + 1

    def test_move_to_position(self, sample_df: pd.DataFrame) -> None:
        result = execute_move_column(sample_df, {"column": "age", "position": 0})
        assert list(result.columns)[0] == "age"

    def test_default_moves_to_front(self, sample_df: pd.DataFrame) -> None:
        result = execute_move_column(sample_df, {"column": "score"})
        assert list(result.columns)[0] == "score"


# ── execute_split_column ──────────────────────────────────────────────────────


class TestSplitColumn:
    def test_split_with_new_names(self) -> None:
        df = pd.DataFrame({"full_name": ["Alice Smith", "Bob Jones"]})
        result = execute_split_column(
            df, {"column": "full_name", "delimiter": " ", "new_names": ["first", "last"]}
        )
        assert result["first"].iloc[0] == "Alice"
        assert result["last"].iloc[0] == "Smith"

    def test_split_auto_names(self) -> None:
        df = pd.DataFrame({"code": ["A-1", "B-2"]})
        result = execute_split_column(df, {"column": "code", "delimiter": "-"})
        assert "code_1" in result.columns
        assert "code_2" in result.columns

    def test_drop_original(self) -> None:
        df = pd.DataFrame({"full_name": ["Alice Smith"]})
        result = execute_split_column(
            df,
            {"column": "full_name", "delimiter": " ", "new_names": ["first", "last"], "drop_original": True},
        )
        assert "full_name" not in result.columns


# ── execute_drop_duplicates ───────────────────────────────────────────────────


class TestDropDuplicates:
    def test_drops_all_column_duplicates(self, sample_df: pd.DataFrame) -> None:
        result = execute_drop_duplicates(sample_df, {})
        assert len(result) == 3  # "Bob" row at idx 1 and 3 are identical

    def test_drops_subset_duplicates(self, sample_df: pd.DataFrame) -> None:
        result = execute_drop_duplicates(sample_df, {"columns": ["name"]})
        assert len(result["name"].unique()) == len(result)

    def test_keep_last(self, sample_df: pd.DataFrame) -> None:
        result = execute_drop_duplicates(sample_df, {"keep": "last"})
        # The last Bob (index 3) should be kept
        assert result[result["name"] == "Bob"].index[0] == 2  # reset_index makes it 2


# ── execute_fill_nulls ────────────────────────────────────────────────────────


class TestFillNulls:
    def test_fill_with_value(self, sample_df: pd.DataFrame) -> None:
        result = execute_fill_nulls(sample_df, {"column": "city", "value": "Unknown"})
        assert result["city"].isna().sum() == 0
        assert "Unknown" in result["city"].values

    def test_fill_with_mean(self) -> None:
        df = pd.DataFrame({"val": [1.0, None, 3.0]})
        result = execute_fill_nulls(df, {"column": "val", "method": "mean"})
        assert result["val"].iloc[1] == pytest.approx(2.0)

    def test_fill_with_median(self) -> None:
        df = pd.DataFrame({"val": [1.0, None, 3.0, 5.0]})
        result = execute_fill_nulls(df, {"column": "val", "method": "median"})
        assert result["val"].isna().sum() == 0

    def test_fill_with_mode(self) -> None:
        df = pd.DataFrame({"cat": ["a", None, "a", "b"]})
        result = execute_fill_nulls(df, {"column": "cat", "method": "mode"})
        assert result["cat"].isna().sum() == 0

    def test_neither_value_nor_method_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="required"):
            execute_fill_nulls(sample_df, {"column": "city"})


# ── execute_cast_type ─────────────────────────────────────────────────────────


class TestCastType:
    def test_cast_to_string(self, sample_df: pd.DataFrame) -> None:
        result = execute_cast_type(sample_df, {"column": "age", "dtype": "string"})
        assert result["age"].iloc[0] == "30"

    def test_cast_to_float(self) -> None:
        df = pd.DataFrame({"val": ["1.5", "2.5"]})
        result = execute_cast_type(df, {"column": "val", "dtype": "float"})
        assert result["val"].iloc[0] == pytest.approx(1.5)

    def test_cast_to_int(self, sample_df: pd.DataFrame) -> None:
        result = execute_cast_type(sample_df, {"column": "age", "dtype": "integer"})
        assert str(result["age"].dtype) == "Int64"

    def test_cast_to_datetime(self) -> None:
        df = pd.DataFrame({"date": ["2026-01-01", "2026-06-15"]})
        result = execute_cast_type(df, {"column": "date", "dtype": "datetime"})
        assert pd.api.types.is_datetime64_any_dtype(result["date"])

    def test_unknown_dtype_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="Unknown dtype"):
            execute_cast_type(sample_df, {"column": "age", "dtype": "uuid"})


# ── execute_reorder_columns ───────────────────────────────────────────────────


class TestReorderColumns:
    def test_reorders_to_given_order(self, sample_df: pd.DataFrame) -> None:
        result = execute_reorder_columns(sample_df, {"order": ["score", "name", "age", "city"]})
        assert list(result.columns) == ["score", "name", "age", "city"]

    def test_partial_order_appends_remaining(self, sample_df: pd.DataFrame) -> None:
        result = execute_reorder_columns(sample_df, {"order": ["score", "name"]})
        cols = list(result.columns)
        assert cols[0] == "score"
        assert cols[1] == "name"
        assert set(cols) == set(sample_df.columns)

    def test_empty_order_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="required"):
            execute_reorder_columns(sample_df, {"order": []})

    def test_missing_column_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError):
            execute_reorder_columns(sample_df, {"order": ["salary", "name"]})


# ── execute_operations (dispatch) ─────────────────────────────────────────────


class TestExecuteOperations:
    def test_sequential_operations(self, sample_df: pd.DataFrame) -> None:
        ops = [
            {"op_type": "delete_columns", "params": {"columns": ["city"]}},
            {"op_type": "sort", "params": {"column": "age", "ascending": True}},
        ]
        result = execute_operations(sample_df, ops)
        assert "city" not in result.columns
        assert list(result["age"]) == sorted(result["age"])

    def test_unknown_op_type_raises(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ManipulationError, match="Unknown operation"):
            execute_operations(sample_df, [{"op_type": "explode", "params": {}}])

    def test_empty_operations_returns_copy(self, sample_df: pd.DataFrame) -> None:
        result = execute_operations(sample_df, [])
        assert result.equals(sample_df)
        assert result is not sample_df
