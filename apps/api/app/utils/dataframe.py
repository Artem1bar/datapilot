"""Shared DataFrame I/O utilities."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

# Marker used to make missing values explicit in LLM-facing samples. Plain
# ``df.fillna("")`` collapses genuine empty strings and nulls into the same
# empty cell, so a model reading the sample cannot tell "" apart from a missing
# value and mis-plans null handling. Rendering nulls as this sentinel keeps the
# distinction visible in both markdown tables and JSON.
NULL_SENTINEL = "<null>"


def read_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Read *file_bytes* into a DataFrame based on *filename*'s extension.

    Supports CSV, TSV/TAB, XLS/XLSX, Parquet, and JSON.
    Any unrecognised extension falls back to CSV.
    """
    lower = filename.lower()
    buf = io.BytesIO(file_bytes)
    if lower.endswith((".xls", ".xlsx")):
        return pd.read_excel(buf)
    if lower.endswith(".parquet"):
        return pd.read_parquet(buf)
    if lower.endswith((".tsv", ".tab")):
        return pd.read_csv(buf, sep="\t")
    if lower.endswith(".json"):
        return pd.read_json(buf)
    return pd.read_csv(buf)


def to_sample_records(df: pd.DataFrame, null_marker: str = NULL_SENTINEL) -> list[dict[str, Any]]:
    """Convert *df* into row dicts for an LLM sample, keeping nulls explicit.

    Unlike ``df.fillna("")``, this preserves the distinction between a genuine
    empty string (``""``) and a missing value (rendered as *null_marker*), so a
    model reading the sample can plan null handling correctly. All other values
    are passed through unchanged.
    """
    if df.empty:
        return []
    # Cast to object first so a string marker can replace nulls in numeric or
    # datetime columns without dtype errors; keep non-null cells as-is.
    masked = df.astype(object).where(df.notna(), null_marker)
    return masked.to_dict(orient="records")
