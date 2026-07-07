"""Shared DataFrame I/O utilities."""

from __future__ import annotations

import io

import pandas as pd


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
