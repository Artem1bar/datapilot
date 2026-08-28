"""The shape of one computed analysis result, and the plumbing to build it.

Extracted so that descriptive execution (:mod:`app.services.analysis_executor`)
and inferential execution (:mod:`app.services.analysis_inference`) share one
result type without importing each other.

The invariant this module exists to hold: a result is never just a number. It
carries how many rows it saw, how many it excluded, and why — so a mean over
442 of 480 rows is reported as exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from app.services.analysis_stats import json_safe

# Result tables are capped so a groupby over a high-cardinality column cannot
# return 50,000 rows to the UI or the narrator prompt.
MAX_RESULT_ROWS = 200

# A result that never came from a spec's operations list, and so has no
# planned parameters to attribute to it.
UNPLANNED = -1


class ExecutionError(RuntimeError):
    """An operation failed at runtime despite passing validation."""


@dataclass(frozen=True)
class OperationResult:
    """One computed table, with the provenance needed to report it honestly."""

    op: str
    label: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    n: int
    n_excluded: int = 0
    notes: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    # Which entry of the spec's "operations" list produced this result.
    # ``execute_spec`` drops failed operations, so a result's position in the
    # returned list is not its position in the plan. Anything that looks back
    # at the plan — the methods note's parameters, the chart's target — must
    # key on this instead of on the list index, or everything after the first
    # failure is attributed to the wrong operation.
    spec_index: int = UNPLANNED

    def planned_at(self, index: int) -> bool:
        """Whether this result came from ``spec["operations"][index]``."""
        return self.spec_index == index

    def to_table(self) -> dict[str, Any]:
        """Render as the API's table shape (unchanged from the previous contract)."""
        return {"columns": self.columns, "rows": self.rows, "total_rows": self.total_rows}


def to_python(value: Any) -> Any:
    """Coerce numpy/pandas scalars to JSON-safe Python values."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        as_float = float(value)
        return json_safe(as_float)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value) if np.isscalar(value) else False:
        return None
    return value if isinstance(value, (str, int)) else str(value)


def round_or_none(value: Any, places: int = 4) -> float | None:
    """Round a statistic to a JSON-safe value. See :func:`json_safe`."""
    return json_safe(value, places)


def clean_stats(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively replace non-finite floats in a statistics payload with None."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            cleaned[key] = value
        elif isinstance(value, float):
            cleaned[key] = round_or_none(value, 6)
        elif isinstance(value, dict):
            cleaned[key] = clean_stats(value)
        elif isinstance(value, list):
            cleaned[key] = [clean_stats(v) if isinstance(v, dict) else to_python(v) for v in value]
        else:
            cleaned[key] = value
    return cleaned


def frame_to_result(
    df: pd.DataFrame,
    *,
    op: str,
    label: str,
    n: int,
    n_excluded: int = 0,
    notes: list[str] | None = None,
    stats_payload: dict[str, Any] | None = None,
    spec_index: int = UNPLANNED,
) -> OperationResult:
    """Package a result frame, truncating to ``MAX_RESULT_ROWS``."""
    total = len(df)
    truncated = df.head(MAX_RESULT_ROWS)
    all_notes = list(notes or [])
    if total > MAX_RESULT_ROWS:
        all_notes.append(f"Showing the first {MAX_RESULT_ROWS} of {total} result rows.")
    return OperationResult(
        op=op,
        label=label,
        columns=[str(c) for c in truncated.columns],
        rows=[[to_python(v) for v in row] for row in truncated.itertuples(index=False, name=None)],
        total_rows=total,
        n=n,
        n_excluded=n_excluded,
        notes=all_notes,
        stats=clean_stats(stats_payload) if stats_payload else {},
        spec_index=spec_index,
    )


def with_spec_index(result: OperationResult, index: int) -> OperationResult:
    """Stamp a result with the spec operation it came from."""
    return replace(result, spec_index=index)
