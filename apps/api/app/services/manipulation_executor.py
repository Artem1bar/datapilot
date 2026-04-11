"""Pure pandas operations for spreadsheet manipulation.

Each function takes a DataFrame and operation params, returns a new DataFrame.
Never mutates the input DataFrame.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class ManipulationError(Exception):
    """Raised when a manipulation operation fails."""


def _validate_columns_exist(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ManipulationError(f"Columns not found: {missing}. Available: {list(df.columns[:20])}")


def execute_delete_columns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    columns = params.get("columns", [])
    if not columns:
        raise ManipulationError("No columns specified for deletion")
    _validate_columns_exist(df, columns)
    return df.drop(columns=columns)


def execute_rename_column(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    old_name = params.get("old_name", "")
    new_name = params.get("new_name", "")
    if not old_name or not new_name:
        raise ManipulationError("Both old_name and new_name are required")
    _validate_columns_exist(df, [old_name])
    if new_name in df.columns:
        raise ManipulationError(f"Column '{new_name}' already exists")
    return df.rename(columns={old_name: new_name})


def execute_sort(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    ascending = params.get("ascending", True)
    if not column:
        raise ManipulationError("Column name required for sort")
    _validate_columns_exist(df, [column])
    return df.sort_values(by=column, ascending=ascending, ignore_index=True)


def execute_filter_rows(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    operator = params.get("operator", "")
    value = params.get("value")
    if not column or not operator:
        raise ManipulationError("Column and operator are required for filtering")
    _validate_columns_exist(df, [column])

    series = df[column]
    ops = {
        ">": lambda s, v: s > v,
        ">=": lambda s, v: s >= v,
        "<": lambda s, v: s < v,
        "<=": lambda s, v: s <= v,
        "==": lambda s, v: s == v,
        "!=": lambda s, v: s != v,
        "contains": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
        "not_contains": lambda s, v: ~s.astype(str).str.contains(str(v), case=False, na=False),
        "is_null": lambda s, v: s.isna(),
        "is_not_null": lambda s, v: s.notna(),
    }
    if operator not in ops:
        raise ManipulationError(f"Unknown operator: {operator}. Supported: {list(ops.keys())}")

    # Try numeric comparison
    if operator in (">", ">=", "<", "<="):
        try:
            value = float(value)
            series = pd.to_numeric(series, errors="coerce")
        except (ValueError, TypeError):
            pass

    mask = ops[operator](series, value)
    return df[mask].reset_index(drop=True)


def execute_add_column(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    name = params.get("name", "")
    default_value = params.get("default_value")
    source_columns = params.get("source_columns", [])

    if not name:
        raise ManipulationError("Column name is required")
    if name in df.columns:
        raise ManipulationError(f"Column '{name}' already exists")

    result = df.copy()

    if source_columns and len(source_columns) >= 2:
        # Sum or concatenate source columns
        op = params.get("operation", "sum")
        _validate_columns_exist(df, source_columns)
        if op == "sum":
            result[name] = sum(pd.to_numeric(result[c], errors="coerce").fillna(0) for c in source_columns)
        elif op == "concat":
            separator = params.get("separator", " ")
            result[name] = result[source_columns[0]].astype(str)
            for c in source_columns[1:]:
                result[name] = result[name] + separator + result[c].astype(str)
        else:
            raise ManipulationError(f"Unknown operation: {op}")
    elif default_value is not None:
        result[name] = default_value
    else:
        result[name] = pd.NA

    return result


def execute_merge_columns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    columns = params.get("columns", [])
    separator = params.get("separator", " ")
    new_name = params.get("new_name", "")
    drop_originals = params.get("drop_originals", False)

    if len(columns) < 2:
        raise ManipulationError("At least 2 columns required for merge")
    if not new_name:
        raise ManipulationError("new_name is required")
    _validate_columns_exist(df, columns)

    result = df.copy()
    result[new_name] = result[columns[0]].astype(str)
    for c in columns[1:]:
        result[new_name] = result[new_name] + separator + result[c].astype(str)

    if drop_originals:
        result = result.drop(columns=[c for c in columns if c != new_name])

    return result


def execute_format_column(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    format_type = params.get("format_type", "")
    _validate_columns_exist(df, [column])

    result = df.copy()
    if format_type == "currency":
        result[column] = pd.to_numeric(result[column], errors="coerce").apply(
            lambda x: f"${x:,.2f}" if pd.notna(x) else ""
        )
    elif format_type == "percentage":
        result[column] = pd.to_numeric(result[column], errors="coerce").apply(
            lambda x: f"{x:.1f}%" if pd.notna(x) else ""
        )
    elif format_type == "integer":
        result[column] = pd.to_numeric(result[column], errors="coerce").apply(
            lambda x: str(int(x)) if pd.notna(x) else ""
        )
    elif format_type == "lowercase":
        result[column] = result[column].astype(str).str.lower()
    elif format_type == "uppercase":
        result[column] = result[column].astype(str).str.upper()
    elif format_type == "titlecase":
        result[column] = result[column].astype(str).str.title()
    elif format_type == "trim":
        result[column] = result[column].astype(str).str.strip()
    else:
        raise ManipulationError(f"Unknown format_type: {format_type}")
    return result


def execute_move_column(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    before = params.get("before")
    after = params.get("after")
    position = params.get("position")  # integer index

    _validate_columns_exist(df, [column])

    cols = list(df.columns)
    cols.remove(column)

    if before and before in df.columns:
        idx = cols.index(before)
    elif after and after in df.columns:
        idx = cols.index(after) + 1
    elif position is not None:
        idx = max(0, min(int(position), len(cols)))
    else:
        idx = 0  # Move to front by default

    cols.insert(idx, column)
    return df[cols]


def execute_split_column(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    delimiter = params.get("delimiter", ",")
    new_names = params.get("new_names", [])
    drop_original = params.get("drop_original", False)

    _validate_columns_exist(df, [column])

    result = df.copy()
    split_df = result[column].astype(str).str.split(delimiter, expand=True)

    if new_names:
        for i, name in enumerate(new_names):
            if i < split_df.shape[1]:
                result[name] = split_df[i].str.strip()
    else:
        for i in range(split_df.shape[1]):
            result[f"{column}_{i+1}"] = split_df[i].str.strip()

    if drop_original:
        result = result.drop(columns=[column])

    return result


def execute_drop_duplicates(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    columns = params.get("columns")
    keep = params.get("keep", "first")
    if columns:
        _validate_columns_exist(df, columns)
    return df.drop_duplicates(subset=columns, keep=keep).reset_index(drop=True)


def execute_fill_nulls(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    value = params.get("value")
    method = params.get("method")  # "mean", "median", "mode", "ffill", "bfill"

    _validate_columns_exist(df, [column])
    result = df.copy()

    if method == "mean":
        fill_val = pd.to_numeric(result[column], errors="coerce").mean()
        result[column] = result[column].fillna(fill_val)
    elif method == "median":
        fill_val = pd.to_numeric(result[column], errors="coerce").median()
        result[column] = result[column].fillna(fill_val)
    elif method == "mode":
        mode_val = result[column].mode()
        if len(mode_val) > 0:
            result[column] = result[column].fillna(mode_val.iloc[0])
    elif method in ("ffill", "bfill"):
        result[column] = result[column].fillna(method=method)
    elif value is not None:
        result[column] = result[column].fillna(value)
    else:
        raise ManipulationError("Either value or method is required for fill_nulls")

    return result


def execute_cast_type(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("column", "")
    dtype = params.get("dtype", "")
    _validate_columns_exist(df, [column])

    result = df.copy()
    try:
        if dtype in ("int", "integer"):
            result[column] = pd.to_numeric(result[column], errors="coerce").astype("Int64")
        elif dtype in ("float", "number"):
            result[column] = pd.to_numeric(result[column], errors="coerce")
        elif dtype in ("str", "string", "text"):
            result[column] = result[column].astype(str)
        elif dtype in ("datetime", "date"):
            result[column] = pd.to_datetime(result[column], errors="coerce")
        elif dtype == "bool":
            result[column] = result[column].astype(bool)
        else:
            raise ManipulationError(f"Unknown dtype: {dtype}")
    except Exception as e:
        raise ManipulationError(f"Failed to cast '{column}' to {dtype}: {e}")

    return result


def execute_reorder_columns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    order = params.get("order", [])
    if not order:
        raise ManipulationError("Column order list is required")
    _validate_columns_exist(df, order)
    # Keep any columns not in the order at the end
    remaining = [c for c in df.columns if c not in order]
    return df[order + remaining]


# ── Operation dispatch ─────────────────────────────────────────────────────

OPERATION_MAP = {
    "delete_columns": execute_delete_columns,
    "rename_column": execute_rename_column,
    "sort": execute_sort,
    "filter_rows": execute_filter_rows,
    "add_column": execute_add_column,
    "merge_columns": execute_merge_columns,
    "format_column": execute_format_column,
    "move_column": execute_move_column,
    "split_column": execute_split_column,
    "drop_duplicates": execute_drop_duplicates,
    "fill_nulls": execute_fill_nulls,
    "cast_type": execute_cast_type,
    "reorder_columns": execute_reorder_columns,
}


def execute_operations(df: pd.DataFrame, operations: list[dict[str, Any]]) -> pd.DataFrame:
    """Execute a sequence of manipulation operations on a DataFrame.

    Each operation is applied in order. Never mutates the original DataFrame.
    """
    result = df.copy()
    for i, op in enumerate(operations):
        op_type = op.get("op_type", "")
        params = op.get("params", {})

        executor = OPERATION_MAP.get(op_type)
        if executor is None:
            raise ManipulationError(f"Step {i+1}: Unknown operation '{op_type}'")

        try:
            result = executor(result, params)
            logger.info("Step %d: %s completed (%d rows, %d cols)", i + 1, op_type, len(result), len(result.columns))
        except ManipulationError:
            raise
        except Exception as e:
            raise ManipulationError(f"Step {i+1} [{op_type}] failed: {e}")

    return result
