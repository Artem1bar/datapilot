"""Tests for shared DataFrame utilities — especially null-preserving sampling."""

from __future__ import annotations

import pandas as pd

from app.utils.dataframe import NULL_SENTINEL, to_sample_records


def test_to_sample_records_distinguishes_null_from_empty_string():
    df = pd.DataFrame({"note": ["hi", "", None]})
    records = to_sample_records(df)
    assert records[0]["note"] == "hi"
    assert records[1]["note"] == ""  # genuine empty string preserved
    assert records[2]["note"] == NULL_SENTINEL  # missing value made explicit


def test_to_sample_records_marks_numeric_nulls():
    df = pd.DataFrame({"amount": [10.0, None, 30.0]})
    records = to_sample_records(df)
    assert records[0]["amount"] == 10.0
    assert records[1]["amount"] == NULL_SENTINEL
    assert records[2]["amount"] == 30.0


def test_to_sample_records_empty_dataframe_returns_empty_list():
    assert to_sample_records(pd.DataFrame()) == []


def test_to_sample_records_accepts_custom_marker():
    df = pd.DataFrame({"c": [None]})
    assert to_sample_records(df, null_marker="NULL")[0]["c"] == "NULL"
