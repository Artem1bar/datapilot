"""Unit tests for multi-sheet helper functions."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.services.multi_sheet import (
    _read_single,
    get_sheet_summary,
    merge_dataframes,
    read_all_sheets,
)

# ---------------------------------------------------------------------------
# get_sheet_summary
# ---------------------------------------------------------------------------

def test_get_sheet_summary_returns_one_entry_per_sheet() -> None:
    sheets = {
        "A": pd.DataFrame({"x": [1, 2], "y": [3, 4]}),
        "B": pd.DataFrame({"z": [5]}),
    }
    summaries = get_sheet_summary(sheets)
    assert len(summaries) == 2
    names = {s["name"] for s in summaries}
    assert names == {"A", "B"}


def test_get_sheet_summary_row_col_count() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})
    summary = get_sheet_summary({"S": df})[0]
    assert summary["row_count"] == 3
    assert summary["col_count"] == 3


def test_get_sheet_summary_columns_and_dtypes() -> None:
    df = pd.DataFrame({"name": ["alice"], "age": [30]})
    summary = get_sheet_summary({"Sheet1": df})[0]
    assert summary["columns"] == ["name", "age"]
    assert "name" in summary["dtypes"]
    assert "age" in summary["dtypes"]


def test_get_sheet_summary_null_pct_zero_when_no_nulls() -> None:
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    summary = get_sheet_summary({"S": df})[0]
    assert summary["null_pct"] == 0.0


def test_get_sheet_summary_null_pct_nonzero() -> None:
    df = pd.DataFrame({"a": [1, None], "b": [3, 4]})
    summary = get_sheet_summary({"S": df})[0]
    assert summary["null_pct"] > 0.0


def test_get_sheet_summary_empty_dict() -> None:
    assert get_sheet_summary({}) == []


# ---------------------------------------------------------------------------
# merge_dataframes
# ---------------------------------------------------------------------------

def test_merge_concat_stacks_rows() -> None:
    df1 = pd.DataFrame({"a": [1, 2]})
    df2 = pd.DataFrame({"a": [3, 4]})
    result = merge_dataframes([df1, df2], method="concat")
    assert list(result["a"]) == [1, 2, 3, 4]


def test_merge_concat_resets_index() -> None:
    df1 = pd.DataFrame({"a": [1]}, index=[5])
    df2 = pd.DataFrame({"a": [2]}, index=[10])
    result = merge_dataframes([df1, df2], method="concat")
    assert list(result.index) == [0, 1]


def test_merge_concat_mixed_columns_fills_nan() -> None:
    df1 = pd.DataFrame({"a": [1], "b": [2]})
    df2 = pd.DataFrame({"a": [3], "c": [4]})
    result = merge_dataframes([df1, df2], method="concat")
    assert set(result.columns) == {"a", "b", "c"}


def test_merge_join_inner() -> None:
    df1 = pd.DataFrame({"id": [1, 2, 3], "x": [10, 20, 30]})
    df2 = pd.DataFrame({"id": [2, 3, 4], "y": [200, 300, 400]})
    result = merge_dataframes([df1, df2], method="join", on="id", how="inner")
    assert set(result["id"]) == {2, 3}
    assert "x" in result.columns and "y" in result.columns


def test_merge_join_left() -> None:
    df1 = pd.DataFrame({"id": [1, 2], "x": [10, 20]})
    df2 = pd.DataFrame({"id": [2], "y": [200]})
    result = merge_dataframes([df1, df2], method="join", on="id", how="left")
    assert len(result) == 2


def test_merge_empty_list_returns_empty_df() -> None:
    result = merge_dataframes([])
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0


def test_merge_invalid_method_raises() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(ValueError, match="Invalid merge method"):
        merge_dataframes([df], method="unknown")


def test_merge_single_df_concat_returns_same_data() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = merge_dataframes([df], method="concat")
    assert list(result["a"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# _read_single — CSV and TSV
# ---------------------------------------------------------------------------

def _csv_bytes(content: str) -> bytes:
    return content.encode()


def test_read_single_csv() -> None:
    csv = _csv_bytes("col1,col2\n1,2\n3,4\n")
    df = _read_single(csv, "data.csv")
    assert list(df.columns) == ["col1", "col2"]
    assert len(df) == 2


def test_read_single_tsv() -> None:
    tsv = _csv_bytes("a\tb\n1\t2\n")
    df = _read_single(tsv, "data.tsv")
    assert list(df.columns) == ["a", "b"]
    assert df["a"][0] == 1


def test_read_single_tab_extension() -> None:
    tsv = _csv_bytes("x\ty\n5\t6\n")
    df = _read_single(tsv, "data.tab")
    assert list(df.columns) == ["x", "y"]


def test_read_single_json() -> None:
    import json
    data = [{"k": 1}, {"k": 2}]
    json_bytes = json.dumps(data).encode()
    df = _read_single(json_bytes, "data.json")
    assert list(df["k"]) == [1, 2]


def test_read_single_parquet() -> None:
    pytest.importorskip("pyarrow", reason="pyarrow not installed")
    df_orig = pd.DataFrame({"val": [10, 20, 30]})
    buf = io.BytesIO()
    df_orig.to_parquet(buf, index=False, engine="pyarrow")
    df = _read_single(buf.getvalue(), "data.parquet")
    assert list(df["val"]) == [10, 20, 30]


# ---------------------------------------------------------------------------
# read_all_sheets — non-Excel fallback
# ---------------------------------------------------------------------------

def test_read_all_sheets_csv_returns_sheet1() -> None:
    csv = _csv_bytes("a,b\n1,2\n")
    sheets = read_all_sheets(csv, "file.csv")
    assert "Sheet1" in sheets
    assert len(sheets) == 1


def test_read_all_sheets_csv_content_correct() -> None:
    csv = _csv_bytes("x,y\n10,20\n")
    sheets = read_all_sheets(csv, "file.csv")
    df = sheets["Sheet1"]
    assert df["x"][0] == 10
