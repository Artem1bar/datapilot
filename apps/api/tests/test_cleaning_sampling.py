"""Regression tests for the cleaning-plan row sample sent to Claude.

The plan-generation sample previously ran ``df.fillna("")``, collapsing nulls
and empty strings into the same empty cell so the model could not plan null
handling. These tests lock in that nulls stay distinguishable.
"""

from __future__ import annotations

import io

import pandas as pd

from app.routers.cleaning import _read_all_rows
from app.services.cleaning import _sample_rows_to_markdown
from app.utils.dataframe import NULL_SENTINEL


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf)
    return buf.getvalue()


def test_read_all_rows_preserves_null_vs_empty_string():
    df = pd.DataFrame({"note": ["hi", "", None], "amount": [1.0, 2.0, None]})
    rows = _read_all_rows(_parquet_bytes(df), "data.parquet")

    assert [r["note"] for r in rows] == ["hi", "", NULL_SENTINEL]
    assert rows[2]["amount"] == NULL_SENTINEL


def test_markdown_sample_shows_null_marker_and_keeps_empty_cell():
    df = pd.DataFrame({"note": ["hi", "", None]})
    rows = _read_all_rows(_parquet_bytes(df), "data.parquet")
    table = _sample_rows_to_markdown(rows)

    # The null sentinel is visible to the model...
    assert NULL_SENTINEL in table
    # ...and the empty-string row does not render as the sentinel.
    lines = table.splitlines()
    empty_row_line = lines[3]  # header, separator, "hi" row, "" row
    assert NULL_SENTINEL not in empty_row_line
