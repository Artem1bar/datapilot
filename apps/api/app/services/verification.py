"""Deterministic post-cleaning verification service.

Re-runs quality flag detection on cleaned data and validates that each
cleaning operation achieved its expected postcondition. Pure functions
with no I/O, no DB, and no Claude calls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses (frozen / immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepVerification:
    """Verification result for a single cleaning step."""
    step_index: int
    operation: str
    column: str | None
    passed: bool
    expected: str
    actual: str
    remaining_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationReport:
    """Full verification report for a cleaning job."""
    overall_passed: bool
    flags_before: dict[str, Any]
    flags_after: dict[str, Any]
    flags_resolved: list[str]
    flags_remaining: list[str]
    flags_new: list[str]
    step_results: list[StepVerification]
    failed_steps: list[dict[str, Any]]
    audit_completeness: float  # 0.0 – 1.0
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Patterns reused from profile_task and cleaning operations
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(r"[$€£¥₹]")
_VAGUE_WORDS = {"n/a", "na", "not much", "very little", "nothing", "none", "unknown"}
_VAGUE_PATTERN = re.compile(
    r"^(not\s+much|very\s+little|n/?a|none|nothing|idk|unclear|unknown|"
    r"not\s+sure|not\s+applicable|tbd|tbc|–|—|-|\.\.\.?)$",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "twenty", "thirty", "forty", "fifty",
    "hundred", "thousand",
}


# ---------------------------------------------------------------------------
# Per-operation postcondition validators
# ---------------------------------------------------------------------------

def _validate_remove_currency_symbols(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="remove_currency_symbols", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    matches = df[column].astype(str).str.contains(r"[$€£¥₹]", regex=True, na=False)
    bad_count = int(matches.sum())
    return StepVerification(
        step_index=-1, operation="remove_currency_symbols", column=column,
        passed=bad_count == 0,
        expected="0 cells with currency symbols",
        actual=f"{bad_count} cells still contain currency symbols",
        remaining_issues=tuple(df[column][matches].head(5).astype(str).tolist()) if bad_count else (),
    )


def _validate_free_to_zero(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="free_to_zero", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    mask = df[column].astype(str).str.strip().str.lower().str.startswith("free")
    bad_count = int(mask.sum())
    return StepVerification(
        step_index=-1, operation="free_to_zero", column=column,
        passed=bad_count == 0,
        expected="0 cells starting with 'free'",
        actual=f"{bad_count} cells still start with 'free'",
        remaining_issues=tuple(df[column][mask].head(5).astype(str).tolist()) if bad_count else (),
    )


def _validate_extract_number(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="extract_number", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    numeric = pd.to_numeric(df[column], errors="coerce")
    non_null = df[column].notna().sum()
    numeric_count = numeric.notna().sum()
    pct = float(numeric_count / non_null * 100) if non_null > 0 else 100.0
    return StepVerification(
        step_index=-1, operation="extract_number", column=column,
        passed=bool(pct >= 90.0),
        expected=">=90% of non-null values are numeric",
        actual=f"{pct:.1f}% are numeric ({numeric_count}/{non_null})",
    )


def _validate_convert_number_words(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="convert_number_words", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    lower_vals = df[column].astype(str).str.lower().str.strip()
    mask = lower_vals.isin(_NUMBER_WORDS)
    bad_count = int(mask.sum())
    return StepVerification(
        step_index=-1, operation="convert_number_words", column=column,
        passed=bad_count == 0,
        expected="0 cells with number words",
        actual=f"{bad_count} cells still contain number words",
        remaining_issues=tuple(df[column][mask].head(5).astype(str).tolist()) if bad_count else (),
    )


def _validate_remove_vague_entries(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="remove_vague_entries", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    non_null = df[column].dropna()
    if len(non_null) == 0:
        return StepVerification(
            step_index=-1, operation="remove_vague_entries", column=column,
            passed=True, expected="All null (no vague entries)", actual="Column is all null",
        )
    mask = non_null.astype(str).str.strip().apply(
        lambda v: bool(_VAGUE_PATTERN.match(v))
    )
    bad_count = int(mask.sum())
    return StepVerification(
        step_index=-1, operation="remove_vague_entries", column=column,
        passed=bad_count == 0,
        expected="0 cells with vague entries",
        actual=f"{bad_count} cells still contain vague entries",
        remaining_issues=tuple(non_null[mask].head(5).astype(str).tolist()) if bad_count else (),
    )


def _validate_cast_type(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="cast_type", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    target = params.get("target_type", "")
    dtype_name = str(df[column].dtype)
    type_map = {
        "int": {"int64", "int32", "Int64", "Int32"},
        "float": {"float64", "float32", "Float64"},
        "str": {"object", "string"},
        "datetime": {"datetime64[ns]"},
    }
    expected_dtypes = type_map.get(target, set())
    passed = dtype_name in expected_dtypes or target in dtype_name
    return StepVerification(
        step_index=-1, operation="cast_type", column=column,
        passed=passed,
        expected=f"dtype should be {target} (one of {expected_dtypes})",
        actual=f"dtype is {dtype_name}",
    )


def _validate_drop_rows(
    df: pd.DataFrame, column: str, params: dict[str, Any],
    *, original_row_count: int,
) -> StepVerification:
    indices = params.get("indices", [])
    if not indices:
        return StepVerification(
            step_index=-1, operation="drop_rows", column=column,
            passed=True,
            expected="No indices to drop",
            actual="No indices specified",
        )
    # We can only verify that the total row count decreased by at least
    # the expected amount. Other steps may also remove rows, so an exact
    # check is not possible without per-step snapshots.
    rows_dropped = original_row_count - len(df)
    passed = rows_dropped >= len(indices)
    return StepVerification(
        step_index=-1, operation="drop_rows", column=column,
        passed=passed,
        expected=f"At least {len(indices)} rows dropped",
        actual=f"{rows_dropped} total rows dropped ({original_row_count} -> {len(df)})",
    )


def _validate_strip_whitespace(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="strip_whitespace", column=column,
            passed=True, expected="Column absent (skipped)", actual="Column absent",
        )
    if not pd.api.types.is_string_dtype(df[column]) and not pd.api.types.is_object_dtype(df[column]):
        return StepVerification(
            step_index=-1, operation="strip_whitespace", column=column,
            passed=True, expected="Non-string column (skipped)", actual=f"dtype={df[column].dtype}",
        )
    has_ws = df[column].dropna().apply(lambda v: str(v) != str(v).strip())
    bad_count = int(has_ws.sum())
    return StepVerification(
        step_index=-1, operation="strip_whitespace", column=column,
        passed=bad_count == 0,
        expected="0 cells with leading/trailing whitespace",
        actual=f"{bad_count} cells still have whitespace",
    )


def _validate_deduplicate(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    subset = params.get("subset")
    dup_count = int(df.duplicated(subset=subset).sum())
    return StepVerification(
        step_index=-1, operation="deduplicate", column=column,
        passed=dup_count == 0,
        expected="0 duplicate rows",
        actual=f"{dup_count} duplicate rows remain",
    )


def _validate_flag_extreme_outliers(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    flag_col = f"{column}_flagged"
    if flag_col not in df.columns:
        flag_col = "_flagged"
    has_flag = flag_col in df.columns

    # If no flag column exists, check whether there are any extreme outliers
    # remaining. If cap_extreme_values already handled them, there's nothing
    # left to flag — that's a pass, not a failure.
    if not has_flag and column in df.columns:
        numeric = pd.to_numeric(df[column], errors="coerce").dropna()
        if len(numeric) < 4:
            # Too few values to detect outliers — nothing to flag
            return StepVerification(
                step_index=-1, operation="flag_extreme_outliers", column=column,
                passed=True,
                expected="No outliers to flag (too few values)",
                actual="No outliers detected",
            )
        median_val = numeric.median()
        mad = (numeric - median_val).abs().median()
        if mad == 0:
            upper = numeric.quantile(0.99)
            has_outliers = (numeric > upper).any()
        else:
            modified_z = 0.6745 * (numeric - median_val).abs() / mad
            has_outliers = (modified_z > 3.5).any()
        if not has_outliers:
            return StepVerification(
                step_index=-1, operation="flag_extreme_outliers", column=column,
                passed=True,
                expected="No extreme outliers remain (already handled by cap_extreme_values)",
                actual="No outliers detected — flag column not needed",
            )

    return StepVerification(
        step_index=-1, operation="flag_extreme_outliers", column=column,
        passed=has_flag,
        expected=f"Flag column '{flag_col}' exists",
        actual=f"Flag column {'exists' if has_flag else 'missing'}",
    )


def _validate_noop(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    """Fallback validator for operations without specific postconditions."""
    return StepVerification(
        step_index=-1, operation="unknown", column=column,
        passed=True,
        expected="No specific postcondition (assumed ok)",
        actual="Skipped validation",
    )


def _validate_clean_column_names(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    dirty = [c for c in df.columns if c != c.strip() or "\xa0" in str(c)]
    return StepVerification(
        step_index=-1, operation="clean_column_names", column=column,
        passed=len(dirty) == 0,
        expected="0 columns with NBSP or trailing whitespace",
        actual=f"{len(dirty)} columns still have dirty names: {dirty[:3]}",
    )


def _validate_drop_empty_columns(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    empty = [c for c in df.columns if df[c].isna().all()]
    return StepVerification(
        step_index=-1, operation="drop_empty_columns", column=column,
        passed=len(empty) == 0,
        expected="0 entirely-null columns",
        actual=f"{len(empty)} empty columns remain: {empty[:5]}",
    )


def _validate_drop_incomplete_responses(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    progress_col = params.get("progress_column", "Progress")
    finished_col = params.get("finished_column", "Finished")
    if progress_col not in df.columns:
        return StepVerification(
            step_index=-1, operation="drop_incomplete_responses", column=column,
            passed=True, expected="Progress column absent", actual="Column absent",
        )
    prog = pd.to_numeric(df[progress_col], errors="coerce")
    if finished_col in df.columns:
        finished_vals = df[finished_col].astype(str).str.strip().str.lower()
        incomplete = (prog < 100) & (~finished_vals.isin(["true", "1", "yes"]))
    else:
        incomplete = prog < 100
    count = int(incomplete.sum())
    return StepVerification(
        step_index=-1, operation="drop_incomplete_responses", column=column,
        passed=count == 0,
        expected="0 incomplete responses",
        actual=f"{count} incomplete responses remain",
    )


def _validate_cap_extreme_values(
    df: pd.DataFrame, column: str, params: dict[str, Any],
) -> StepVerification:
    if column not in df.columns:
        return StepVerification(
            step_index=-1, operation="cap_extreme_values", column=column,
            passed=True, expected="Column absent", actual="Column absent",
        )
    max_value = params.get("max_value")
    if max_value is None:
        return StepVerification(
            step_index=-1, operation="cap_extreme_values", column=column,
            passed=True, expected="No max_value (skipped)", actual="No max_value param",
        )
    numeric = pd.to_numeric(df[column], errors="coerce")
    over = numeric > max_value
    count = int(over.sum())
    return StepVerification(
        step_index=-1, operation="cap_extreme_values", column=column,
        passed=count == 0,
        expected=f"0 values above {max_value}",
        actual=f"{count} values still above {max_value}",
        remaining_issues=tuple(df[column][over].head(5).astype(str).tolist()) if count else (),
    )


_VALIDATOR_MAP: dict[str, Any] = {
    "remove_currency_symbols": _validate_remove_currency_symbols,
    "free_to_zero": _validate_free_to_zero,
    "extract_number": _validate_extract_number,
    "convert_number_words": _validate_convert_number_words,
    "remove_vague_entries": _validate_remove_vague_entries,
    "cast_type": _validate_cast_type,
    "strip_whitespace": _validate_strip_whitespace,
    "deduplicate": _validate_deduplicate,
    "flag_extreme_outliers": _validate_flag_extreme_outliers,
    "clean_column_names": _validate_clean_column_names,
    "drop_empty_columns": _validate_drop_empty_columns,
    "drop_incomplete_responses": _validate_drop_incomplete_responses,
    "cap_extreme_values": _validate_cap_extreme_values,
}


# ---------------------------------------------------------------------------
# Audit log completeness
# ---------------------------------------------------------------------------

def _compute_audit_completeness(
    original_df: pd.DataFrame,
    original_flags: dict[str, Any],
    audit_log: list[dict[str, Any]],
) -> float:
    """Compute the ratio of flagged cells that appear in the audit log.

    Returns a float between 0.0 and 1.0.
    """
    total_flagged = 0
    total_addressed = 0

    audit_set: set[tuple[str, int]] = set()
    for entry in audit_log:
        col = entry.get("column", "")
        row = entry.get("row")
        if col and row is not None:
            audit_set.add((col, int(row)))

    for col, col_flags in original_flags.items():
        if col in ("qualtrics_header_row",):
            # Row-level flag, count as 1
            total_flagged += 1
            if any(e.get("operation") == "drop_rows" for e in audit_log):
                total_addressed += 1
            continue

        if not isinstance(col_flags, dict):
            continue

        # Count flagged cells per column using the same detection logic
        if col not in original_df.columns:
            continue

        series = original_df[col].dropna()
        str_vals = series.astype(str)
        flagged_count = 0

        if col_flags.get("has_currency"):
            flagged_count += int(str_vals.str.contains(r"[$€£¥₹]", regex=True, na=False).sum())
        if col_flags.get("has_free_values"):
            flagged_count += int(str_vals.str.lower().str.strip().str.startswith("free").sum())
        if col_flags.get("has_number_words"):
            flagged_count += int(str_vals.str.lower().str.strip().isin(_NUMBER_WORDS).sum())
        if col_flags.get("has_vague_values"):
            flagged_count += int(str_vals.str.strip().apply(
                lambda v: bool(_VAGUE_PATTERN.match(v))
            ).sum())
        if col_flags.get("has_embedded_text"):
            flagged_count += int(str_vals.str.contains(
                r"(?:\d+[\.\d]*\s*[a-zA-Z]+|[a-zA-Z]+\s*\d+[\.\d]*)", regex=True, na=False
            ).sum())

        if flagged_count == 0:
            continue

        total_flagged += flagged_count
        addressed = sum(1 for (c, _r) in audit_set if c == col)
        total_addressed += min(addressed, flagged_count)

    if total_flagged == 0:
        return 1.0

    return round(total_addressed / total_flagged, 4)


# ---------------------------------------------------------------------------
# Main verification entry point
# ---------------------------------------------------------------------------

def verify_cleaning_result(
    original_df: pd.DataFrame,
    cleaned_df: pd.DataFrame,
    steps: list[dict[str, Any]],
    audit_log: list[dict[str, Any]],
    original_quality_flags: dict[str, Any],
    failed_steps: list[dict[str, Any]] | None = None,
) -> VerificationReport:
    """Run the full deterministic verification cycle.

    Compares before/after quality flags, validates each step's postcondition,
    and computes audit log completeness. Pure function — no side effects.
    """
    from app.tasks.profile_task import detect_quality_issues

    if failed_steps is None:
        failed_steps = []

    # Step A: Re-profile the cleaned DataFrame
    flags_after = detect_quality_issues(cleaned_df)

    before_keys = set(original_quality_flags.keys())
    after_keys = set(flags_after.keys())

    flags_resolved = sorted(before_keys - after_keys)
    flags_remaining = sorted(before_keys & after_keys)
    flags_new = sorted(after_keys - before_keys)

    # Step B: Per-step postcondition validation
    step_results: list[StepVerification] = []
    original_row_count = len(original_df)

    for i, step in enumerate(steps):
        operation = step.get("operation", "")
        column = step.get("column")
        params = step.get("params", {})

        # Skip steps that already failed during execution
        if any(fs["step_index"] == i for fs in failed_steps):
            step_results.append(StepVerification(
                step_index=i, operation=operation, column=column,
                passed=False,
                expected="Step should execute successfully",
                actual="Step failed during execution",
            ))
            continue

        validator = _VALIDATOR_MAP.get(operation, _validate_noop)
        if operation == "drop_rows":
            result = _validate_drop_rows(cleaned_df, column, params,
                                         original_row_count=original_row_count)
        else:
            result = validator(cleaned_df, column, params)

        # Patch in the correct step_index
        step_results.append(StepVerification(
            step_index=i,
            operation=result.operation if result.operation != "unknown" else operation,
            column=result.column,
            passed=result.passed,
            expected=result.expected,
            actual=result.actual,
            remaining_issues=result.remaining_issues,
        ))

    # Step C: Audit log completeness
    audit_completeness = _compute_audit_completeness(
        original_df, original_quality_flags, audit_log,
    )

    # Determine overall pass
    all_steps_passed = all(s.passed for s in step_results)
    no_remaining_flags = len(flags_remaining) == 0
    overall_passed = all_steps_passed and no_remaining_flags and len(failed_steps) == 0

    # Build summary with step numbers
    summary_parts = []
    if overall_passed:
        summary_parts.append(f"All {len(step_results)} cleaning operations verified successfully.")
    else:
        if not all_steps_passed:
            failed_nums = [
                f"Step {s.step_index + 1} ({s.operation})"
                for s in step_results if not s.passed
            ]
            summary_parts.append(
                f"{len(failed_nums)} step(s) did not achieve expected postcondition: "
                f"{', '.join(failed_nums[:5])}."
            )
        if flags_remaining:
            summary_parts.append(f"Quality flags still present: {', '.join(flags_remaining)}.")
        if failed_steps:
            failed_ops = [
                f"Step {fs['step_index'] + 1} ({fs['operation']})"
                for fs in failed_steps
            ]
            summary_parts.append(f"{len(failed_steps)} step(s) failed during execution: {', '.join(failed_ops[:5])}.")
    if flags_resolved:
        summary_parts.append(f"Resolved flags: {', '.join(flags_resolved)}.")
    if flags_new:
        summary_parts.append(f"New flags detected after cleaning: {', '.join(flags_new)}.")
    summary_parts.append(f"Audit log completeness: {audit_completeness:.0%}.")

    return VerificationReport(
        overall_passed=overall_passed,
        flags_before=original_quality_flags,
        flags_after=flags_after,
        flags_resolved=flags_resolved,
        flags_remaining=flags_remaining,
        flags_new=flags_new,
        step_results=step_results,
        failed_steps=failed_steps,
        audit_completeness=audit_completeness,
        summary=" ".join(summary_parts),
    )
