"""Multi-sheet and multi-file support for datasets."""
from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def read_all_sheets(file_bytes: bytes, filename: str) -> dict[str, pd.DataFrame]:
    """Read all sheets from an Excel file. Returns {sheet_name: DataFrame}."""
    if not filename.lower().endswith((".xlsx", ".xls")):
        # For non-Excel files, return single "Sheet1"
        df = _read_single(file_bytes, filename)
        return {"Sheet1": df}

    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        sheets = {}
        for name in xls.sheet_names:
            sheets[name] = pd.read_excel(xls, sheet_name=name)
        return sheets
    except Exception as e:
        logger.error("Failed to read sheets: %s", e)
        return {"Sheet1": pd.read_excel(io.BytesIO(file_bytes))}


def get_sheet_summary(sheets: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Return summary info for each sheet."""
    summaries = []
    for name, df in sheets.items():
        summaries.append({
            "name": name,
            "row_count": len(df),
            "col_count": len(df.columns),
            "columns": list(df.columns),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "null_pct": round(float(df.isna().mean().mean()) * 100, 2),
        })
    return summaries


def merge_dataframes(
    dfs: list[pd.DataFrame],
    method: str = "concat",
    on: str | list[str] | None = None,
    how: str = "inner",
) -> pd.DataFrame:
    """Merge multiple DataFrames.

    Methods:
    - concat: Vertical concatenation (stack rows)
    - join: Horizontal join on key column(s)
    """
    if not dfs:
        return pd.DataFrame()

    if method == "concat":
        return pd.concat(dfs, ignore_index=True, sort=False)

    if method == "join" and on:
        result = dfs[0]
        for df in dfs[1:]:
            result = result.merge(df, on=on, how=how, suffixes=("", "_dup"))
        return result

    raise ValueError(f"Invalid merge method: {method}")


def _read_single(file_bytes: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes))
    elif lower.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(file_bytes))
    elif lower.endswith((".tsv", ".tab")):
        return pd.read_csv(io.BytesIO(file_bytes), sep="\t")
    elif lower.endswith(".json"):
        return pd.read_json(io.BytesIO(file_bytes))
    return pd.read_csv(io.BytesIO(file_bytes))
