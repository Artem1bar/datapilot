"""Dataset comparison service — diff two datasets."""
from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compare_datasets(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    max_sample: int = 100,
) -> dict[str, Any]:
    """Compare two DataFrames and return a structured diff report."""
    report: dict[str, Any] = {
        "summary": {},
        "columns": {},
        "row_changes": {},
        "statistical_drift": [],
        "sample_changes": [],
    }

    # Column-level changes
    before_cols = set(df_before.columns)
    after_cols = set(df_after.columns)
    added_cols = sorted(after_cols - before_cols)
    removed_cols = sorted(before_cols - after_cols)
    common_cols = sorted(before_cols & after_cols)

    report["columns"] = {
        "added": added_cols,
        "removed": removed_cols,
        "common": common_cols,
        "before_count": len(before_cols),
        "after_count": len(after_cols),
    }

    report["summary"] = {
        "rows_before": len(df_before),
        "rows_after": len(df_after),
        "rows_added": max(0, len(df_after) - len(df_before)),
        "rows_removed": max(0, len(df_before) - len(df_after)),
        "columns_added": len(added_cols),
        "columns_removed": len(removed_cols),
    }

    # Statistical drift for common numeric columns
    for col in common_cols:
        if pd.api.types.is_numeric_dtype(df_before[col]) and pd.api.types.is_numeric_dtype(df_after[col]):
            before_desc = df_before[col].describe()
            after_desc = df_after[col].describe()

            before_mean = float(before_desc.get("mean", 0))
            after_mean = float(after_desc.get("mean", 0))
            before_std = float(before_desc.get("std", 0))
            after_std = float(after_desc.get("std", 0))

            mean_shift = after_mean - before_mean
            pct_change = (mean_shift / before_mean * 100) if before_mean != 0 else 0

            if abs(pct_change) > 5:  # Only report meaningful drift
                report["statistical_drift"].append({
                    "column": col,
                    "before_mean": round(before_mean, 4),
                    "after_mean": round(after_mean, 4),
                    "mean_shift": round(mean_shift, 4),
                    "pct_change": round(pct_change, 2),
                    "before_std": round(before_std, 4),
                    "after_std": round(after_std, 4),
                    "before_null_pct": round(float(df_before[col].isna().mean()) * 100, 2),
                    "after_null_pct": round(float(df_after[col].isna().mean()) * 100, 2),
                })

    # Cell-level changes (sample)
    min_rows = min(len(df_before), len(df_after), max_sample)
    changes = []
    for i in range(min_rows):
        for col in common_cols:
            before_val = df_before.iloc[i].get(col)
            after_val = df_after.iloc[i].get(col) if col in df_after.columns else None
            if not _values_equal(before_val, after_val):
                changes.append({
                    "row": i,
                    "column": col,
                    "before": _safe_value(before_val),
                    "after": _safe_value(after_val),
                })
        if len(changes) >= 200:
            break

    report["sample_changes"] = changes
    report["summary"]["cells_changed"] = len(changes)

    # Type changes
    type_changes = []
    for col in common_cols:
        before_type = str(df_before[col].dtype)
        after_type = str(df_after[col].dtype)
        if before_type != after_type:
            type_changes.append({
                "column": col,
                "before_type": before_type,
                "after_type": after_type,
            })
    report["columns"]["type_changes"] = type_changes

    return report


def _values_equal(a: Any, b: Any) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return a == b


def _safe_value(val: Any) -> Any:
    if pd.isna(val):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return val
