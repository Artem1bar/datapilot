"""Regression tests for JSONB serialization of DataFrame-derived payloads.

Live QA (2026-07-09) found the clean job crashing at the final
``UPDATE jobs SET result_json`` when a ``cast_type`` step converted a column
to datetime: ``pd.Timestamp`` values from ``df.to_dict(orient="records")``
reached the stdlib JSON encoder, which rejects them. Both SQLAlchemy engines
now share a pandas/numpy-aware serializer (``app.utils.json.dumps_json``).
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.utils.json import dumps_json, sanitize_for_json


class TestSanitizeForJson:
    def test_pandas_timestamp_becomes_iso_string(self):
        assert sanitize_for_json(pd.Timestamp("2026-01-15")) == "2026-01-15T00:00:00"

    def test_nat_becomes_none(self):
        assert sanitize_for_json(pd.NaT) is None

    def test_datetime_and_date_become_iso_strings(self):
        assert sanitize_for_json(datetime(2026, 1, 15, 8, 30)) == "2026-01-15T08:30:00"
        assert sanitize_for_json(date(2026, 1, 15)) == "2026-01-15"

    def test_numpy_scalars_become_python_scalars(self):
        assert sanitize_for_json(np.int64(7)) == 7
        assert sanitize_for_json(np.float64(1.5)) == 1.5
        assert sanitize_for_json(np.bool_(True)) is True

    def test_nan_and_infinity_become_none(self):
        # Postgres JSONB rejects NaN/Infinity literals, so they must not
        # survive serialization.
        assert sanitize_for_json(float("nan")) is None
        assert sanitize_for_json(float("inf")) is None
        assert sanitize_for_json(np.float64("nan")) is None

    def test_ndarray_becomes_list(self):
        assert sanitize_for_json(np.array([1, 2, 3])) == [1, 2, 3]

    def test_decimal_and_uuid(self):
        assert sanitize_for_json(Decimal("1.25")) == 1.25
        uid = uuid.uuid4()
        assert sanitize_for_json(uid) == str(uid)

    def test_nested_containers_are_recursed(self):
        payload = {
            "rows": [{"order_date": pd.Timestamp("2026-01-15"), "qty": np.int64(2)}],
            "stats": (np.float64(0.5), None),
        }
        assert sanitize_for_json(payload) == {
            "rows": [{"order_date": "2026-01-15T00:00:00", "qty": 2}],
            "stats": [0.5, None],
        }

    def test_non_string_dict_keys_are_stringified(self):
        assert sanitize_for_json({0: "a", np.int64(1): "b"}) == {"0": "a", "1": "b"}

    def test_plain_json_values_pass_through(self):
        payload = {"a": 1, "b": "x", "c": [True, None, 2.5]}
        assert sanitize_for_json(payload) == payload

    def test_unknown_objects_fall_back_to_str(self):
        class Weird:
            def __str__(self) -> str:
                return "weird"

        assert sanitize_for_json(Weird()) == "weird"


class TestDumpsJson:
    def test_cleaning_result_shaped_payload_round_trips(self):
        """The exact failure shape from live QA: sample rows after a
        datetime cast, embedded in the job result payload."""
        df = pd.DataFrame(
            {
                "order_date": pd.to_datetime(["2026-01-15", "01/17/2026"], format="mixed"),
                "unit_price": [19.99, np.nan],
                "quantity": np.array([2, 3], dtype=np.int64),
            }
        )
        payload = {
            "cleaned_rows": 13,
            "verification": {
                "cleaned_sample_rows": df.to_dict(orient="records"),
                "overall_passed": np.bool_(True),
            },
        }

        parsed = json.loads(dumps_json(payload))

        assert parsed["cleaned_rows"] == 13
        rows = parsed["verification"]["cleaned_sample_rows"]
        assert rows[0]["order_date"] == "2026-01-15T00:00:00"
        assert rows[1]["unit_price"] is None  # NaN → null, not a crash
        assert parsed["verification"]["overall_passed"] is True

    def test_output_contains_no_nan_or_infinity_literals(self):
        out = dumps_json({"x": float("nan"), "y": float("inf"), "z": [math.inf]})
        assert "NaN" not in out
        assert "Infinity" not in out

    def test_stdlib_dumps_rejects_what_dumps_json_accepts(self):
        """Documents why the shared serializer exists."""
        with pytest.raises(TypeError):
            json.dumps({"ts": pd.Timestamp("2026-01-15")})
        dumps_json({"ts": pd.Timestamp("2026-01-15")})  # must not raise


class TestEngineWiring:
    def test_sync_engine_serializes_timestamps(self):
        """The Celery-side engine must use dumps_json for JSONB writes."""
        from app.tasks._db import get_sync_engine

        serializer = get_sync_engine().dialect._json_serializer
        assert serializer is not None
        out = serializer({"ts": pd.Timestamp("2026-01-15")})
        assert "2026-01-15T00:00:00" in out

    def test_async_engine_serializes_timestamps(self):
        """The API-side engine must use dumps_json for JSONB writes."""
        from app.db.engine import engine

        serializer = engine.dialect._json_serializer
        assert serializer is not None
        out = serializer({"ts": pd.Timestamp("2026-01-15")})
        assert "2026-01-15T00:00:00" in out
