"""Shared vocabulary for the analysis operation registry.

Extracted from :mod:`app.services.analysis_spec` so a tier module can declare
its own operations beside the code that executes them without importing the
validator that gates them — which would be a cycle, since the validator has to
import the tier modules to assemble the whitelist.

Three things live here:

* :class:`ColumnRoles` — what the dataset actually contains, built from the
  dataframe rather than the stored profile so validation always reflects the
  file being analyzed.
* :class:`Param` and :class:`OperationDef` — how an operation declares itself
  to both the planner prompt and the validator. Declaring once is the point:
  :func:`app.services.analysis_spec.describe_capabilities` renders the prompt
  from the same objects the validator enforces, so the two cannot drift.
* :class:`SpecError` — the failure raised when a model's spec cannot be made
  valid.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import pandas as pd

# Bounds on category discovery. Knowing a column's actual values lets the
# validator reject a filter on "Weest" or a success_value of "Yes" when the data
# says "yes" — a rejection the model can act on, instead of an empty result it
# cannot explain. The cost is a hash pass per text column, so it is capped.
MAX_CATEGORY_VALUES = 50
MAX_CATEGORY_COLUMNS = 30
MAX_CATEGORY_ROWS = 200_000

_EMPTY_CATEGORIES: Mapping[str, frozenset[str]] = MappingProxyType({})


@dataclass(frozen=True)
class ColumnRoles:
    """Which columns exist and what may be done with them.

    Built from the dataframe itself rather than the stored profile, so
    validation always reflects the file being analyzed.
    """

    all: frozenset[str]
    numeric: frozenset[str]
    datetime: frozenset[str]
    # Distinct values of low-cardinality text columns, as strings. Empty for a
    # column that is high-cardinality or beyond the discovery bounds — in which
    # case value membership is simply not checked.
    categories: Mapping[str, frozenset[str]] = field(default=_EMPTY_CATEGORIES)

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> ColumnRoles:
        numeric = frozenset(str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c]))
        datetime = frozenset(
            str(c) for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])
        )
        return cls(
            all=frozenset(str(c) for c in df.columns),
            numeric=numeric,
            datetime=datetime,
            categories=_discover_categories(df, numeric | datetime),
        )


def _discover_categories(df: pd.DataFrame, skip: frozenset[str]) -> Mapping[str, frozenset[str]]:
    """Collect the distinct values of low-cardinality, non-numeric columns."""
    if len(df) > MAX_CATEGORY_ROWS:
        return _EMPTY_CATEGORIES

    found: dict[str, frozenset[str]] = {}
    for column in df.columns:
        if len(found) >= MAX_CATEGORY_COLUMNS:
            break
        name = str(column)
        if name in skip:
            continue
        values = df[column].dropna().unique()
        if 0 < len(values) <= MAX_CATEGORY_VALUES:
            found[name] = frozenset(str(value) for value in values)
    return MappingProxyType(found)


class SpecError(ValueError):
    """The model's analysis spec could not be validated."""


# ---------------------------------------------------------------------------
# Operation declarations
# ---------------------------------------------------------------------------
#
# Parameter kinds, enforced by ``_validate_param`` in
# :mod:`app.services.analysis_spec`:
#
#   "column"      — a single column that must exist
#   "columns"     — a non-empty list of columns that must exist
#   "numeric"     — a single column that must exist and be numeric
#   "numerics"    — a non-empty list of existing numeric columns
#   "datetime"    — a single column that must exist and be datetime-typed
#   "agg"         — a member of ALL_AGGS
#   "int"         — a positive integer
#   "count"       — a non-negative integer (an ARIMA order may be zero)
#   "bool"        — a boolean
#   "method"      — a member of CORRELATION_METHODS
#   "freq"        — a member of RESAMPLE_FREQS
#   "choice"      — a member of the parameter's own ``choices``
#   "number"      — any finite number
#   "proportion"  — a number strictly between 0 and 1
#   "text"        — a non-empty string
#   "value"       — a scalar drawn from the data (a category label, say)


@dataclass(frozen=True)
class Param:
    """One declared parameter of an operation."""

    name: str
    kind: str
    required: bool = False
    choices: tuple[str, ...] = ()

    def render(self) -> str:
        rendered = f"{self.name}: "
        rendered += "|".join(self.choices) if self.choices else self.kind
        return rendered if self.required else f"{rendered} (optional)"


# A cross-parameter check: conditional requirements a flat parameter list
# cannot express, such as "a paired t-test needs column2".
Check = Callable[[dict[str, Any], ColumnRoles], list[str]]


@dataclass(frozen=True)
class OperationDef:
    """One executable operation, as the planner sees it and the validator gates it."""

    tier: int
    summary: str
    params: tuple[Param, ...]
    # Conditional rules, in prompt text. Kept beside the check that enforces
    # them so the prompt cannot describe a rule the validator does not apply.
    requires: str = ""
    check: Check | None = None
