"""Unit tests for the export service."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.services.export import export_to_csv, export_to_json, export_to_parquet, export_to_xlsx


@pytest.fixture()
def sample_df():
    return pd.DataFrame({"name": ["Alice", "Bob"], "score": [90, 75], "active": [True, False]})


class TestExportToCsv:
    def test_returns_bytes(self, sample_df):
        result = export_to_csv(sample_df)
        assert isinstance(result, bytes)

    def test_contains_header_and_rows(self, sample_df):
        result = export_to_csv(sample_df).decode()
        assert "name" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_column_filter(self, sample_df):
        result = export_to_csv(sample_df, columns=["name"]).decode()
        assert "name" in result
        assert "score" not in result
        assert "active" not in result

    def test_column_filter_preserves_order(self, sample_df):
        result = export_to_csv(sample_df, columns=["score", "name"]).decode()
        lines = result.strip().splitlines()
        assert lines[0].startswith("score")

    def test_no_index_column(self, sample_df):
        result = export_to_csv(sample_df).decode()
        assert not result.startswith("0,")
        assert not result.startswith(",")

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": pd.Series([], dtype="float64")})
        result = export_to_csv(df).decode()
        assert "a" in result


class TestExportToXlsx:
    def test_returns_bytes(self, sample_df):
        result = export_to_xlsx(sample_df)
        assert isinstance(result, bytes)
        assert result[:4] == b"PK\x03\x04"  # xlsx is a zip

    def test_column_filter(self, sample_df):
        result = export_to_xlsx(sample_df, columns=["name"])
        df_out = pd.read_excel(io.BytesIO(result))
        assert list(df_out.columns) == ["name"]

    def test_roundtrip(self, sample_df):
        result = export_to_xlsx(sample_df)
        df_out = pd.read_excel(io.BytesIO(result))
        assert list(df_out.columns) == list(sample_df.columns)
        assert len(df_out) == len(sample_df)

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": pd.Series([], dtype="float64")})
        result = export_to_xlsx(df)
        df_out = pd.read_excel(io.BytesIO(result))
        assert list(df_out.columns) == ["a"]
        assert len(df_out) == 0


class TestExportToJson:
    def test_returns_bytes(self, sample_df):
        result = export_to_json(sample_df)
        assert isinstance(result, bytes)

    def test_records_orientation(self, sample_df):
        import json

        result = json.loads(export_to_json(sample_df))
        assert isinstance(result, list)
        assert result[0]["name"] == "Alice"
        assert result[1]["score"] == 75

    def test_column_filter(self, sample_df):
        import json

        result = json.loads(export_to_json(sample_df, columns=["name"]))
        assert all("score" not in r for r in result)
        assert all("name" in r for r in result)

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": pd.Series([], dtype="float64")})
        import json

        result = json.loads(export_to_json(df))
        assert result == []


class TestExportToParquet:
    def test_returns_bytes(self, sample_df):
        result = export_to_parquet(sample_df)
        assert isinstance(result, bytes)
        assert result[:4] == b"PAR1"  # parquet magic

    def test_roundtrip(self, sample_df):
        result = export_to_parquet(sample_df)
        df_out = pd.read_parquet(io.BytesIO(result))
        assert list(df_out.columns) == list(sample_df.columns)
        assert len(df_out) == len(sample_df)

    def test_column_filter(self, sample_df):
        result = export_to_parquet(sample_df, columns=["name", "score"])
        df_out = pd.read_parquet(io.BytesIO(result))
        assert set(df_out.columns) == {"name", "score"}

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": pd.Series([], dtype="float64")})
        result = export_to_parquet(df)
        df_out = pd.read_parquet(io.BytesIO(result))
        assert list(df_out.columns) == ["a"]
        assert len(df_out) == 0
