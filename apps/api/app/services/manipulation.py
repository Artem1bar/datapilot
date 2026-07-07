"""Spreadsheet manipulation service — parses natural language commands into structured operations."""

from __future__ import annotations

import io
import json
import logging
import uuid
from typing import Any

import anthropic
import pandas as pd

from app.config import settings
from app.services.manipulation_executor import ManipulationError, execute_operations
from app.services.storage import download_file_bytes, upload_file_bytes
from app.utils.dataframe import read_dataframe

logger = logging.getLogger(__name__)

_anthropic_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Return a lazily-initialized Anthropic client singleton."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    return _anthropic_client


_SYSTEM_PROMPT = """You are a data manipulation assistant. Given a user command and dataset context (column names, dtypes, sample rows), parse the command into a list of structured operations.

Return ONLY a JSON array of operations. Each operation has:
- "op_type": one of: delete_columns, rename_column, sort, filter_rows, add_column, merge_columns, format_column, move_column, split_column, drop_duplicates, fill_nulls, cast_type, reorder_columns
- "params": operation-specific parameters (see below)
- "description": human-readable description of what this operation does

Operation params:
- delete_columns: {"columns": ["col1", "col2"]}
- rename_column: {"old_name": "old", "new_name": "new"}
- sort: {"column": "col", "ascending": true/false}
- filter_rows: {"column": "col", "operator": ">|>=|<|<=|==|!=|contains|not_contains|is_null|is_not_null", "value": ...}
- add_column: {"name": "new_col", "source_columns": ["a", "b"], "operation": "sum|concat", "separator": " ", "default_value": null}
- merge_columns: {"columns": ["col1", "col2"], "separator": " ", "new_name": "merged", "drop_originals": false}
- format_column: {"column": "col", "format_type": "currency|percentage|integer|lowercase|uppercase|titlecase|trim"}
- move_column: {"column": "col", "before": "other_col" | "after": "other_col" | "position": 0}
- split_column: {"column": "col", "delimiter": ",", "new_names": ["part1", "part2"], "drop_original": false}
- drop_duplicates: {"columns": ["col1"] | null, "keep": "first|last"}
- fill_nulls: {"column": "col", "value": ... | "method": "mean|median|mode|ffill|bfill"}
- cast_type: {"column": "col", "dtype": "int|float|str|datetime|bool"}
- reorder_columns: {"order": ["col3", "col1", "col2"]}

IMPORTANT:
- Use EXACT column names from the dataset context (case-sensitive)
- If the user refers to a column by a slightly different name, fuzzy-match to the closest actual column name
- For compound commands (e.g., "delete X and Y, then rename Z"), return multiple operations
- If the command is ambiguous, make your best guess and add a clear description
- Return ONLY the JSON array, no markdown, no explanation"""


def _dataframe_to_bytes(df: pd.DataFrame, filename: str) -> bytes:
    buf = io.BytesIO()
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        df.to_excel(buf, index=False)
    elif lower.endswith(".parquet"):
        df.to_parquet(buf, index=False)
    elif lower.endswith(".tsv"):
        df.to_csv(buf, index=False, sep="\t")
    elif lower.endswith(".json"):
        df.to_json(buf, orient="records")
    else:
        df.to_csv(buf, index=False)
    return buf.getvalue()


def parse_manipulation_intent(
    command: str,
    column_names: list[str],
    dtypes: dict[str, str],
    sample_rows: list[dict],
) -> list[dict[str, Any]]:
    """Call Claude to parse a natural language command into structured operations."""
    client = _get_client()

    context = (
        f"Dataset columns ({len(column_names)}): {json.dumps(column_names)}\n"
        f"Column types: {json.dumps(dtypes)}\n"
        f"Sample rows (first 5):\n{json.dumps(sample_rows[:5], default=str)}"
    )

    response = client.messages.create(
        model=settings.MANIPULATION_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Dataset context:\n{context}\n\nCommand: {command}"},
        ],
    )

    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        operations = json.loads(text)
    except json.JSONDecodeError as e:
        raise ManipulationError(f"Failed to parse AI response: {e}\nResponse: {text[:500]}")

    if not isinstance(operations, list):
        raise ManipulationError("AI returned non-list response")

    return operations


def generate_preview(
    df: pd.DataFrame,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute operations on a copy and return before/after preview."""
    before_sample = df.head(5).fillna("").to_dict(orient="records")
    before_cols = list(df.columns)
    before_rows = len(df)

    result_df = execute_operations(df, operations)
    after_sample = result_df.head(5).fillna("").to_dict(orient="records")
    after_cols = list(result_df.columns)

    affected_columns = list(set(before_cols) ^ set(after_cols))
    for op in operations:
        col = op.get("params", {}).get("column")
        if col and col not in affected_columns:
            affected_columns.append(col)

    warnings = []
    removed_cols = set(before_cols) - set(after_cols)
    if removed_cols:
        warnings.append(
            f"Will delete {len(removed_cols)} column(s): {', '.join(sorted(removed_cols))}"
        )
    rows_removed = before_rows - len(result_df)
    if rows_removed > 0:
        warnings.append(f"Will remove {rows_removed} row(s)")

    return {
        "operations": operations,
        "preview_before": before_sample,
        "preview_after": after_sample,
        "affected_columns": affected_columns,
        "affected_row_count": abs(before_rows - len(result_df)),
        "warnings": warnings,
        "confirmation_required": bool(removed_cols) or rows_removed > len(df) * 0.1,
    }


def create_snapshot(r2_key: str) -> tuple[str, str]:
    """Create a backup snapshot of the current dataset file in R2."""
    snapshot_id = str(uuid.uuid4())
    snapshot_key = f"snapshots/{snapshot_id}/{r2_key.split('/')[-1]}"
    file_bytes = download_file_bytes(r2_key)
    upload_file_bytes(snapshot_key, file_bytes)
    logger.info("Created snapshot %s for %s", snapshot_id, r2_key)
    return snapshot_id, snapshot_key


def apply_manipulation(
    file_bytes: bytes,
    filename: str,
    operations: list[dict[str, Any]],
    r2_key: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute operations on the dataset and upload the result.

    Returns (result_df, metadata).
    """
    df = read_dataframe(file_bytes, filename)
    before_cols = set(df.columns)

    result_df = execute_operations(df, operations)

    # Upload result
    result_bytes = _dataframe_to_bytes(result_df, filename)
    upload_file_bytes(r2_key, result_bytes)

    after_cols = set(result_df.columns)

    return result_df, {
        "new_row_count": len(result_df),
        "new_col_count": len(result_df.columns),
        "columns_added": sorted(after_cols - before_cols),
        "columns_removed": sorted(before_cols - after_cols),
        "columns_renamed": {
            op["params"]["old_name"]: op["params"]["new_name"]
            for op in operations
            if op.get("op_type") == "rename_column"
        },
    }
