"""Export service: convert DataFrames to various file formats."""

from __future__ import annotations

import io

import pandas as pd

# Leading characters that make a spreadsheet cell execute as a formula when the
# file is opened in Excel or Google Sheets (CSV/formula injection). Tab and CR
# are included because they can also introduce a formula context.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_cell(value: object) -> object:
    """Prefix a single quote to any string cell that would execute as a formula."""
    if isinstance(value, str) and value[:1] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def _sanitize_for_spreadsheet(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with formula-triggering string cells neutralized.

    Only object/string columns can carry a formula trigger, so numeric, boolean,
    and datetime columns are left untouched (and never accidentally quoted).
    """
    text_cols = [
        c
        for c in df.columns
        if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c])
    ]
    if not text_cols:
        return df
    df = df.copy()
    for col in text_cols:
        df[col] = df[col].map(_neutralize_cell)
    return df


def export_to_csv(df: pd.DataFrame, columns: list[str] | None = None) -> bytes:
    """Export DataFrame to CSV bytes (formula-injection safe)."""
    if columns is not None:
        df = df[columns]
    buf = io.BytesIO()
    _sanitize_for_spreadsheet(df).to_csv(buf, index=False)
    return buf.getvalue()


def export_to_xlsx(df: pd.DataFrame, columns: list[str] | None = None) -> bytes:
    """Export DataFrame to Excel (xlsx) bytes (formula-injection safe)."""
    if columns is not None:
        df = df[columns]
    buf = io.BytesIO()
    _sanitize_for_spreadsheet(df).to_excel(buf, index=False, engine="openpyxl")
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
