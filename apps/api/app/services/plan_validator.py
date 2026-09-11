"""Pre-execution validation for AI-generated cleaning plans.

Catches hallucinated operations, references to nonexistent columns, and
missing/mistyped required params BEFORE a plan (or an agent remediation step)
reaches the executor — so problems surface as regenerable feedback instead of
silently failed steps mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.cleaning_catalog import (
    column_optional_operations,
    enum_choices,
    required_param_types,
    requires_one_of,
)

# Both tables come from the operation catalogue, so the fields the review card
# offers a person and the fields this validator insists on cannot drift apart.
# Operations that legitimately run without a target column.
COLUMN_OPTIONAL_OPS = column_optional_operations()

# Required params (name, expected type) per operation.
_REQUIRED_PARAMS: dict[str, tuple[tuple[str, type | tuple[type, ...]], ...]] = (
    required_param_types()
)

# Params where one of a group must be supplied, e.g. fill_null's strategy/value.
_REQUIRED_ONE_OF: dict[str, tuple[tuple[str, ...], ...]] = requires_one_of()

_CAST_TARGETS = set(enum_choices("cast_type", "target_type"))


@dataclass(frozen=True)
class PlanIssue:
    """A single validation problem in a cleaning plan step."""

    step_index: int
    field: str  # "operation" | "column" | "params"
    message: str

    def __str__(self) -> str:
        return f"Step {self.step_index + 1} [{self.field}]: {self.message}"


def _normalize_column(name: Any) -> str:
    """Normalize a column name the same way clean_column_names does."""
    cleaned = str(name).replace("\xa0", " ").strip()
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned


def validate_plan(
    steps: list[Any],
    known_operations: set[str],
    columns: list[str],
) -> list[PlanIssue]:
    """Validate cleaning steps against the operation registry and dataset columns.

    Returns a list of issues (empty = valid). Column names are compared in
    normalized form because plans are usually written against
    post-clean_column_names names while the dataset may still have dirty ones.
    Columns created by earlier steps (renames, flag columns) count as available
    for later steps.
    """
    issues: list[PlanIssue] = []
    available = {_normalize_column(c) for c in columns}

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            issues.append(PlanIssue(i, "operation", "Step is not a JSON object"))
            continue

        operation = step.get("operation")
        if not operation or operation not in known_operations:
            issues.append(
                PlanIssue(
                    i,
                    "operation",
                    f"Unknown operation '{operation}'. Supported operations: "
                    f"{', '.join(sorted(known_operations))}",
                )
            )
            continue

        params = step.get("params") or {}
        if not isinstance(params, dict):
            issues.append(PlanIssue(i, "params", "params must be a JSON object"))
            params = {}

        column = step.get("column")
        if operation not in COLUMN_OPTIONAL_OPS:
            if not column or not isinstance(column, str):
                issues.append(
                    PlanIssue(
                        i,
                        "column",
                        f"Operation '{operation}' requires a target column",
                    )
                )
            elif _normalize_column(column) not in available:
                issues.append(
                    PlanIssue(
                        i,
                        "column",
                        f"Column '{column}' does not exist in the dataset",
                    )
                )

        for name, expected in _REQUIRED_PARAMS.get(operation, ()):
            value = params.get(name)
            if value is None:
                issues.append(
                    PlanIssue(
                        i,
                        "params",
                        f"Operation '{operation}' requires param '{name}'",
                    )
                )
            elif not isinstance(value, expected):
                issues.append(
                    PlanIssue(
                        i,
                        "params",
                        f"Param '{name}' has the wrong type",
                    )
                )

        if operation == "drop_rows":
            indices = params.get("indices")
            if isinstance(indices, list) and any(
                not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in indices
            ):
                issues.append(
                    PlanIssue(
                        i,
                        "params",
                        "drop_rows indices must be non-negative integers",
                    )
                )

        if operation == "cast_type":
            target = params.get("target_type")
            if target is not None and target not in _CAST_TARGETS:
                issues.append(
                    PlanIssue(
                        i,
                        "params",
                        f"cast_type target_type must be one of {sorted(_CAST_TARGETS)}",
                    )
                )

        for group in _REQUIRED_ONE_OF.get(operation, ()):
            if all(params.get(name) is None for name in group):
                choices = " or ".join(f"'{name}'" for name in group)
                issues.append(
                    PlanIssue(
                        i,
                        "params",
                        f"{operation} requires either {choices}",
                    )
                )

        # Steps may reference columns created by earlier steps.
        if operation == "rename_column" and isinstance(params.get("new_name"), str):
            available.add(_normalize_column(params["new_name"]))
        if operation in ("flag_extreme_outliers", "flag_contextual_fraud"):
            available.add(_normalize_column(params.get("flag_column", "_flagged")))

    return issues
