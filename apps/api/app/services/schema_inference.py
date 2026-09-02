"""Infer and enforce dataset schemas."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def infer_schema(df: pd.DataFrame) -> dict[str, Any]:
    """Infer a target schema from a DataFrame by analyzing value patterns."""
    schema = {"columns": [], "row_count": len(df)}

    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        col_schema: dict[str, Any] = {
            "name": col,
            "nullable": bool(series.isna().any()),
            "unique": bool(series.nunique() == len(non_null)) if len(non_null) > 0 else False,
        }

        # Infer type
        if pd.api.types.is_integer_dtype(series):
            col_schema["type"] = "integer"
            col_schema["min"] = int(series.min()) if len(non_null) > 0 else None
            col_schema["max"] = int(series.max()) if len(non_null) > 0 else None
        elif pd.api.types.is_float_dtype(series):
            col_schema["type"] = "float"
            col_schema["min"] = float(series.min()) if len(non_null) > 0 else None
            col_schema["max"] = float(series.max()) if len(non_null) > 0 else None
        elif pd.api.types.is_bool_dtype(series):
            col_schema["type"] = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(series):
            col_schema["type"] = "datetime"
        else:
            # String analysis
            if len(non_null) > 0:
                sample = non_null.head(50).astype(str)
                # Check if it's actually numeric
                numeric = pd.to_numeric(sample, errors="coerce")
                if numeric.notna().mean() > 0.8:
                    col_schema["type"] = "numeric_string"
                # Check if it's actually datetime
                elif _is_date_column(sample):
                    col_schema["type"] = "date_string"
                # Check for email pattern
                elif sample.str.match(r"^[a-zA-Z0-9._%+-]+@", na=False).mean() > 0.5:
                    col_schema["type"] = "email"
                # Check for boolean strings
                elif set(non_null.astype(str).str.lower().str.strip()) <= {
                    "true",
                    "false",
                    "yes",
                    "no",
                    "1",
                    "0",
                    "y",
                    "n",
                }:
                    col_schema["type"] = "boolean_string"
                else:
                    col_schema["type"] = "string"
                    unique_count = series.nunique()
                    if unique_count <= 20 and len(non_null) > 10:
                        col_schema["type"] = "categorical"
                        col_schema["allowed_values"] = sorted(
                            non_null.astype(str).unique().tolist()
                        )
                    else:
                        lengths = non_null.astype(str).str.len()
                        col_schema["max_length"] = int(lengths.max())
                        col_schema["avg_length"] = round(float(lengths.mean()), 1)
            else:
                col_schema["type"] = "unknown"

        # Constraints
        constraints = []
        if not col_schema.get("nullable", True):
            constraints.append("NOT NULL")
        if col_schema.get("unique"):
            constraints.append("UNIQUE")
        col_schema["constraints"] = constraints

        schema["columns"].append(col_schema)

    return schema


def validate_against_schema(df: pd.DataFrame, schema: dict) -> list[dict[str, Any]]:
    """Validate a DataFrame against a schema, returning violations."""
    violations = []
    schema_cols = {c["name"]: c for c in schema.get("columns", [])}

    # Check for missing required columns
    for col_name, col_schema in schema_cols.items():
        if col_name not in df.columns:
            violations.append(
                {
                    "type": "missing_column",
                    "column": col_name,
                    "severity": "error",
                    "message": f"Required column '{col_name}' is missing",
                }
            )
            continue

        series = df[col_name]

        # Null check
        if not col_schema.get("nullable", True) and series.isna().any():
            null_count = int(series.isna().sum())
            violations.append(
                {
                    "type": "null_violation",
                    "column": col_name,
                    "severity": "error",
                    "message": f"Column '{col_name}' has {null_count} null values but is NOT NULL",
                    "count": null_count,
                }
            )

        # Type check
        expected_type = col_schema.get("type", "")
        if expected_type == "integer" and not pd.api.types.is_integer_dtype(series):
            non_numeric = pd.to_numeric(series, errors="coerce").isna() & series.notna()
            if non_numeric.any():
                violations.append(
                    {
                        "type": "type_mismatch",
                        "column": col_name,
                        "severity": "warning",
                        "message": f"Column '{col_name}' expected integer but has {int(non_numeric.sum())} non-numeric values",
                        "count": int(non_numeric.sum()),
                    }
                )

        # Range check
        if "min" in col_schema and "max" in col_schema:
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            out_of_range = ((numeric < col_schema["min"]) | (numeric > col_schema["max"])).sum()
            if out_of_range > 0:
                violations.append(
                    {
                        "type": "range_violation",
                        "column": col_name,
                        "severity": "warning",
                        "message": f"Column '{col_name}' has {int(out_of_range)} values outside [{col_schema['min']}, {col_schema['max']}]",
                        "count": int(out_of_range),
                    }
                )

        # Allowed values check
        if "allowed_values" in col_schema:
            allowed = set(col_schema["allowed_values"])
            actual = set(series.dropna().astype(str).unique())
            unexpected = actual - allowed
            if unexpected:
                violations.append(
                    {
                        "type": "value_violation",
                        "column": col_name,
                        "severity": "warning",
                        "message": f"Column '{col_name}' has unexpected values: {list(unexpected)[:5]}",
                        "unexpected_values": list(unexpected)[:10],
                    }
                )

    # Check for unexpected extra columns
    expected_cols = set(schema_cols.keys())
    actual_cols = set(df.columns)
    extra_cols = actual_cols - expected_cols
    for col in extra_cols:
        violations.append(
            {
                "type": "extra_column",
                "column": col,
                "severity": "info",
                "message": f"Unexpected column '{col}' not in schema",
            }
        )

    return violations


def _is_date_column(sample: pd.Series) -> bool:
    """Check if a string series looks like dates."""
    date_count = 0
    for val in sample:
        try:
            pd.to_datetime(str(val))
            date_count += 1
        except (ValueError, TypeError):
            pass
    return date_count > len(sample) * 0.7
