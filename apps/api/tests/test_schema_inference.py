"""Unit tests for schema inference and validation logic."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.schema_inference import infer_schema, validate_against_schema


class TestInferSchemaRowCount:
    def test_row_count(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        schema = infer_schema(df)
        assert schema["row_count"] == 3

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": pd.Series([], dtype="int64")})
        schema = infer_schema(df)
        assert schema["row_count"] == 0
        assert len(schema["columns"]) == 1


class TestInferSchemaTypes:
    def test_integer_column(self):
        df = pd.DataFrame({"age": pd.array([10, 20, 30], dtype="int64")})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "integer"
        assert col["min"] == 10
        assert col["max"] == 30

    def test_float_column(self):
        df = pd.DataFrame({"score": [1.1, 2.2, 3.3]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "float"
        assert col["min"] == pytest.approx(1.1)
        assert col["max"] == pytest.approx(3.3)

    def test_boolean_column(self):
        df = pd.DataFrame({"flag": [True, False, True]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "boolean"

    def test_datetime_column(self):
        df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-01", "2024-06-15"])})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "datetime"

    def test_string_column(self):
        names = [
            "Alice",
            "Bob",
            "Charlie",
            "Dave",
            "Eve",
            "Frank",
            "Grace",
            "Heidi",
            "Ivan",
            "Judy",
            "Karl",
            "Leo",
            "Mallory",
            "Niaj",
            "Olivia",
            "Peggy",
            "Rupert",
            "Sybil",
            "Trent",
            "Victor",
            "Walter",
        ]
        df = pd.DataFrame({"name": names})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "string"
        assert "max_length" in col

    def test_categorical_column(self):
        df = pd.DataFrame({"status": ["active", "inactive", "active"] * 5})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "categorical"
        assert "allowed_values" in col
        assert set(col["allowed_values"]) == {"active", "inactive"}

    def test_numeric_string_column(self):
        df = pd.DataFrame({"zip": ["10001", "10002", "10003"] * 5})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "numeric_string"

    def test_boolean_string_column(self):
        df = pd.DataFrame({"flag": ["yes", "no", "yes", "no"] * 5})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "boolean_string"

    def test_email_column(self):
        df = pd.DataFrame({"email": ["a@b.com", "c@d.org", "e@f.net"] * 5})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "email"

    def test_all_null_column(self):
        df = pd.DataFrame({"x": [None, None, None]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["type"] == "unknown"


class TestInferSchemaNullable:
    def test_non_nullable_column(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["nullable"] is False
        assert "NOT NULL" in col["constraints"]

    def test_nullable_column(self):
        df = pd.DataFrame({"a": [1, None, 3]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["nullable"] is True

    def test_unique_column(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["unique"] is True
        assert "UNIQUE" in col["constraints"]

    def test_non_unique_column(self):
        df = pd.DataFrame({"x": [1, 1, 2]})
        schema = infer_schema(df)
        col = schema["columns"][0]
        assert col["unique"] is False


class TestValidateAgainstSchema:
    def _make_schema(self, df: pd.DataFrame) -> dict:
        return infer_schema(df)

    def test_clean_dataframe_no_violations(self):
        df = pd.DataFrame({"age": pd.array([25, 30, 35], dtype="int64")})
        schema = self._make_schema(df)
        violations = validate_against_schema(df, schema)
        assert violations == []

    def test_missing_column_violation(self):
        df_train = pd.DataFrame({"age": pd.array([25, 30], dtype="int64"), "name": ["a", "b"]})
        schema = self._make_schema(df_train)
        df_test = pd.DataFrame({"age": pd.array([40], dtype="int64")})
        violations = validate_against_schema(df_test, schema)
        types = [v["type"] for v in violations]
        assert "missing_column" in types

    def test_null_violation(self):
        df_train = pd.DataFrame({"age": pd.array([25, 30], dtype="int64")})
        schema = self._make_schema(df_train)
        df_test = pd.DataFrame({"age": [25, None]})
        violations = validate_against_schema(df_test, schema)
        types = [v["type"] for v in violations]
        assert "null_violation" in types

    def test_range_violation(self):
        df_train = pd.DataFrame({"score": [1.0, 2.0, 3.0]})
        schema = self._make_schema(df_train)
        df_test = pd.DataFrame({"score": [1.0, 999.0]})
        violations = validate_against_schema(df_test, schema)
        types = [v["type"] for v in violations]
        assert "range_violation" in types

    def test_value_violation_categorical(self):
        df_train = pd.DataFrame({"status": ["active", "inactive"] * 10})
        schema = self._make_schema(df_train)
        df_test = pd.DataFrame({"status": ["active", "deleted"]})
        violations = validate_against_schema(df_test, schema)
        types = [v["type"] for v in violations]
        assert "value_violation" in types

    def test_extra_column_info(self):
        df_train = pd.DataFrame({"age": pd.array([25, 30], dtype="int64")})
        schema = self._make_schema(df_train)
        df_test = pd.DataFrame({"age": pd.array([25], dtype="int64"), "extra": ["x"]})
        violations = validate_against_schema(df_test, schema)
        types = [v["type"] for v in violations]
        assert "extra_column" in types
        extra = next(v for v in violations if v["type"] == "extra_column")
        assert extra["severity"] == "info"

    def test_violation_severity_levels(self):
        df_train = pd.DataFrame({"id": pd.array([1, 2, 3], dtype="int64")})
        schema = self._make_schema(df_train)
        # Force null violation (error) and extra column (info)
        df_test = pd.DataFrame({"id": [1, None], "bonus": ["x", "y"]})
        violations = validate_against_schema(df_test, schema)
        severities = {v["severity"] for v in violations}
        assert "error" in severities
        assert "info" in severities
