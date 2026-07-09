"""Shared JSON serialization for JSONB columns.

DataFrame-derived payloads (sample rows, audit entries, verification
reports) can carry pandas/numpy scalars that the stdlib encoder rejects —
most notably ``pd.Timestamp`` after a ``cast_type`` step converts a column
to datetime. Postgres additionally rejects ``NaN``/``Infinity`` literals
inside JSONB. Both SQLAlchemy engines pass ``dumps_json`` as their
``json_serializer`` so every JSONB write shares one policy:

- timestamps/dates → ISO strings, ``NaT``/``NaN``/``±inf`` → ``null``
- numpy scalars/arrays → plain Python equivalents
- ``Decimal`` → float, ``UUID`` → string, unknown objects → ``str(obj)``

JSONB here stores display/telemetry payloads, not typed source-of-truth
data (the cleaned dataset itself lives in object storage), so lossy string
fallbacks are preferable to failing a finished job at the persistence step.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import uuid
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def sanitize_for_json(value: Any) -> Any:
    """Recursively convert *value* into plain JSON-compatible types."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_json(v) for v in value]
    if value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta, dt.timedelta)):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [sanitize_for_json(v) for v in value.tolist()]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def dumps_json(value: Any) -> str:
    """Serialize *value* for a JSONB column; never emits NaN/Infinity."""
    return json.dumps(sanitize_for_json(value), allow_nan=False)
