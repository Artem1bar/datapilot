"""Export service: convert DataFrames to various file formats."""

from __future__ import annotations

import io

import pandas as pd


def export_to_csv(df: pd.DataFrame, columns: list[str] | None = None) -> bytes:
    """Export DataFrame to CSV bytes."""
    if columns is not None:
        df = df[columns]
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def export_to_xlsx(df: pd.DataFrame, columns: list[str] | None = None) -> bytes:
    """Export DataFrame to Excel (xlsx) bytes using the openpyxl engine."""
    if columns is not None:
        df = df[columns]
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def export_to_json(df: pd.DataFrame, columns: list[str] | None = None) -> bytes:
    """Export DataFrame to JSON bytes (records orientation)."""
    if columns is not None:
        df = df[columns]
    buf = io.BytesIO()
    df.to_json(buf, orient="records")
    return buf.getvalue()


def export_to_parquet(df: pd.DataFrame, columns: list[str] | None = None) -> bytes:
    """Export DataFrame to Parquet bytes."""
    if columns is not None:
        df = df[columns]
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()
