"""AI-powered data cleaning service.

Uses Claude to generate cleaning plans from dataset profiles and executes
cleaning operations on pandas DataFrames.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "cleaning_system.txt"

# ---------------------------------------------------------------------------
# Anthropic client singleton
# ---------------------------------------------------------------------------

_anthropic_client: Anthropic | None = None


def _get_client() -> Anthropic:
    """Return a lazily-initialized Anthropic client singleton."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY or None)
    return _anthropic_client

# ---------------------------------------------------------------------------
# Number-word lookup table
# ---------------------------------------------------------------------------

_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
}

_NUMBER_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS.keys(), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_TIME_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h|days?|d|minutes?|mins?|m|weeks?|wks?|w)",
    re.IGNORECASE,
)

_CURRENCY_AMOUNT_PATTERN = re.compile(r"\$?\s*(\d+(?:[,\d]*)?(?:\.\d{1,2})?)")


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _load_system_prompt() -> str:
    """Read the cleaning system prompt from disk."""
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _sample_rows_to_markdown(sample_rows: list[dict[str, Any]]) -> str:
    """Convert a list of row dicts into a markdown table."""
    if not sample_rows:
        return "(no sample rows)"
    cols = list(sample_rows[0].keys())
    header = "| " + " | ".join(cols) + " |"
    separator = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for row in sample_rows:
        cells = " | ".join(str(row.get(c, "")) for c in cols)
        rows.append(f"| {cells} |")
    return "\n".join([header, separator, *rows])


def _extract_json_from_response(text: str) -> Any:
    """Extract JSON from a response that may contain markdown code fences."""
    text = text.strip()

    # Strip markdown code fences directly
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            inner = text[first_newline + 1 :]
            last_fence = inner.rfind("```")
            if last_fence != -1:
                inner = inner[:last_fence]
            text = inner.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    break

    raise ValueError(f"Could not extract valid JSON from Claude response: {text[:200]}")


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------


def _build_issues_summary(profile_json: dict[str, Any]) -> str:
    """Convert the data_quality flags from the profile into a human-readable
    directive block that is prepended to the user message for Claude.
    """
    quality = profile_json.get("data_quality", {})
    if not quality:
        return ""

    lines = ["## AUTO-DETECTED ISSUES — YOU MUST ADDRESS EVERY ONE OF THESE\n"]

    # ── Structural issues (run these FIRST) ──

    # Dirty column names
    dirty_names = quality.get("_dirty_column_names")
    if dirty_names:
        cols = dirty_names.get("columns", [])
        lines.append(
            f"- **DIRTY COLUMN NAMES**: {len(cols)} column(s) have non-breaking spaces or trailing whitespace: "
            f"{cols[:5]}. Add a `clean_column_names` step as the VERY FIRST step.\n"
        )

    # Empty columns
    empty_cols = quality.get("_empty_columns")
    if empty_cols:
        cols = empty_cols.get("columns", [])
        lines.append(
            f"- **EMPTY COLUMNS**: {len(cols)} column(s) are 100% null: {cols[:10]}. "
            "Add a `drop_empty_columns` step early.\n"
        )

    # Incomplete survey responses
    incomplete = quality.get("_incomplete_responses")
    if incomplete:
        count = incomplete.get("count", 0)
        lines.append(
            f"- **INCOMPLETE SURVEY RESPONSES**: {count} row(s) have Progress < 100 and Finished != True. "
            "Add a `drop_incomplete_responses` step to remove them.\n"
        )

    # Qualtrics header row
    qr = quality.get("qualtrics_header_row")
    if qr:
        lines.append(
            f"- **QUALTRICS HEADER ROW** at row index {qr['row_index']}: "
            "The first data row contains full question descriptions, not real data. "
            "Add a `drop_rows` step with `params: {{\"indices\": [0]}}` FIRST.\n"
        )

    for col, flags in quality.items():
        if col in ("qualtrics_header_row", "_dirty_column_names", "_empty_columns", "_incomplete_responses") or not isinstance(flags, dict):
            continue
        if flags.get("has_currency"):
            ex = flags.get("currency_examples", [])
            lines.append(
                f"- **{col}** — contains currency symbols (e.g. {ex}). "
                "Use `remove_currency_symbols` then `extract_number` then `cast_type` to float."
            )
        if flags.get("has_embedded_text"):
            ex = flags.get("embedded_text_examples", [])
            lines.append(
                f"- **{col}** — numbers mixed with text (e.g. {ex}). "
                "Use `extract_number` then `cast_type` to float."
            )
        if flags.get("has_free_values"):
            ex = flags.get("free_examples", [])
            lines.append(
                f"- **{col}** — contains 'Free'/'free' values (e.g. {ex}) that should be 0. "
                "Use `free_to_zero` first, then numeric cleaning."
            )
        if flags.get("has_number_words"):
            ex = flags.get("number_word_examples", [])
            lines.append(
                f"- **{col}** — contains number words (e.g. {ex}). "
                "Use `convert_number_words`."
            )
        if flags.get("has_vague_values"):
            ex = flags.get("vague_examples", [])
            lines.append(
                f"- **{col}** — contains vague/unquantifiable entries (e.g. {ex}). "
                "Use `remove_vague_entries`."
            )
        if flags.get("has_extreme_outliers"):
            ex = flags.get("extreme_values", [])
            lines.append(
                f"- **{col}** — contains extreme outlier value(s): {ex}. "
                "Use `flag_extreme_outliers` to null the value and mark the row for review."
            )

    return "\n".join(lines) + "\n\n"


def _filter_sample_rows_to_flagged_columns(
    sample_rows: list[dict[str, Any]],
    data_quality: dict[str, Any],
    max_context_cols: int = 5,
) -> list[dict[str, Any]]:
    """Return sample rows with only the flagged columns + a few context columns.

    Sending all 74 columns overwhelms the model. We only need to show the columns
    that actually have issues plus a handful of identifying context columns.
    """
    if not sample_rows:
        return sample_rows

    all_cols = list(sample_rows[0].keys())

    # Structural meta-keys to skip (they don't correspond to column names)
    _META_KEYS = {"qualtrics_header_row", "_dirty_column_names", "_empty_columns", "_incomplete_responses"}

    # Flagged columns (excluding meta keys)
    flagged = {col for col in data_quality if col not in _META_KEYS and col in all_cols}

    # First few columns as context (dates, IDs, etc.)
    context_cols = all_cols[:max_context_cols]

    # Keep order: context first, then flagged
    keep = list(dict.fromkeys(context_cols + sorted(flagged)))

    return [{col: row[col] for col in keep if col in row} for row in sample_rows]


def generate_cleaning_plan(
    profile_json: dict[str, Any],
    sample_rows: list[dict[str, Any]],
    dataset_id: str | None = None,
    user_instructions: str | None = None,
) -> list[dict[str, Any]]:
    """Send dataset profile and sample rows to Claude and get a cleaning plan.

    Returns a list of CleaningStep dicts with keys:
        operation, column, params, description
    """
    client = _get_client()
    system_prompt = _load_system_prompt()

    # Build the auto-detected issues block — this is the most important signal for Claude
    issues_summary = _build_issues_summary(profile_json)

    # Trim the profile to exclude data_quality (already surfaced in issues_summary)
    profile_for_claude = {k: v for k, v in profile_json.items() if k != "data_quality"}

    data_quality = profile_json.get("data_quality", {})

    # When quality flags exist, focus on flagged columns so the model isn't overwhelmed.
    # When NO flags were detected, send ALL columns — the model must inspect the full data.
    if data_quality:
        focused_rows = _filter_sample_rows_to_flagged_columns(sample_rows, data_quality)
        col_note = "flagged columns"
    else:
        focused_rows = sample_rows[:50]  # send first 50 rows of ALL columns
        col_note = "all columns"
    sample_table = _sample_rows_to_markdown(focused_rows)
    n_samples = len(focused_rows)

    user_message = (
        f"{issues_summary}"
        "Here is the dataset profile:\n\n"
        f"```json\n{json.dumps(profile_for_claude, indent=2, default=str)}\n```\n\n"
        f"Here are {n_samples} sample rows showing {col_note} "
        "(including the header row that needs dropping if flagged):\n\n"
        f"{sample_table}\n\n"
        "Return ONLY a valid JSON object matching the CleaningPlan schema:\n"
        "{\n"
        '  "steps": [\n'
        '    {"operation": "...", "column": "...", "params": {...}, "description": "..."}\n'
        "  ],\n"
        '  "summary": "...",\n'
        '  "estimated_row_impact": null\n'
        "}\n\n"
        "Supported operations:\n"
        "  STRUCTURAL (run first):\n"
        "    clean_column_names — normalise column names (remove NBSP, trim spaces)\n"
        "    drop_empty_columns — drop columns that are 100% null\n"
        "    drop_incomplete_responses — drop rows with Progress < 100 and Finished != True\n"
        "      params: {\"progress_column\": \"Progress\", \"finished_column\": \"Finished\", \"min_progress\": 100}\n"
        "  ROW REMOVAL: drop_rows (params: {\"indices\": [0, 1, ...]}) — drop specific row indices\n"
        "  FORMATTING: strip_whitespace, remove_currency_symbols, extract_number,\n"
        "              convert_number_words, convert_time_to_number\n"
        "  STANDARDIZATION: free_to_zero, remove_vague_entries, standardize_values,\n"
        "                   fill_null, drop_null, cast_type\n"
        "  AGGREGATION: sum_composite_expenses\n"
        "  ANOMALY DETECTION:\n"
        "    flag_extreme_outliers — null out statistical outliers (MAD-based z-score)\n"
        "    cap_extreme_values — null out values above a hard ceiling\n"
        "      params: {\"max_value\": 50000} — USE THIS for obvious data entry errors\n"
        "    flag_contextual_fraud — flag contextually suspicious values\n"
        "  OTHER: deduplicate, rename_column, remove_outliers\n\n"
        "IMPORTANT RULES:\n"
        "- For `drop_rows`, set column to null.\n"
        "- For numeric cleaning, always follow: free_to_zero → remove_currency_symbols → extract_number → cast_type.\n"
        "- For EVERY expense/cost column, add a `cap_extreme_values` step with a reasonable max_value "
        "(e.g. 50000 for hotel, 10000 for meals, 5000 for transport). This catches data entry errors like $1B.\n"
        "- ALWAYS include `flag_extreme_outliers` for numeric expense columns AFTER cap_extreme_values.\n"
        "- Number each step sequentially starting from 1 in the description field (e.g. 'Step 1: ...', 'Step 2: ...').\n"
        "Return ONLY valid JSON. No explanation outside the JSON."
    )

    # Append user-supplied cleaning instructions if provided
    if user_instructions and user_instructions.strip():
        user_message += (
            "\n\n## ADDITIONAL USER INSTRUCTIONS\n"
            "The user has requested the following additional cleaning actions. "
            "Incorporate these into the cleaning plan:\n\n"
            f"{user_instructions.strip()}\n"
        )

    logger.info("Requesting cleaning plan from Claude (model=claude-opus-4-6, flagged_cols=%d)", len(data_quality))
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=16384,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = response.content[0].text
    logger.debug("Claude response: %s", response_text[:500])

    parsed = _extract_json_from_response(response_text)

    if isinstance(parsed, list):
        steps = parsed
    elif isinstance(parsed, dict) and "steps" in parsed:
        steps = parsed["steps"]
    else:
        raise ValueError(f"Unexpected cleaning plan structure: {type(parsed)}")

    # Guard: if quality flags exist but Claude returned no steps, something went wrong
    if not steps and data_quality:
        flagged_cols = [k for k in data_quality if k != "qualtrics_header_row"]
        raise ValueError(
            f"Claude returned 0 cleaning steps despite {len(data_quality)} detected quality issues "
            f"(flagged columns: {flagged_cols[:5]}). Response: {response_text[:300]}"
        )

    validated_steps = []
    for step in steps:
        validated_steps.append({
            "operation": step.get("operation", ""),
            "column": step.get("column"),
            "params": step.get("params", {}),
            "description": step.get("description", ""),
        })

    logger.info("Generated cleaning plan with %d steps", len(validated_steps))
    return validated_steps


# ---------------------------------------------------------------------------
# Audit log helpers
# ---------------------------------------------------------------------------


def _values_semantically_equal(a: Any, b: Any) -> bool:
    """Check if two values are semantically the same despite different types.

    '80' (str) vs 80.0 (float) → True (just a type cast, not a real edit)
    None vs None → True
    'N/a' vs None → False (real change)
    """
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    # Direct equality
    if a == b:
        return True
    # Compare numeric values: "80" == 80.0
    try:
        fa = float(str(a).replace(",", "").strip())
        fb = float(str(b).replace(",", "").strip())
        return fa == fb
    except (ValueError, TypeError):
        pass
    return False


def _diff_column(
    before: pd.Series,
    after: pd.Series,
    column: str,
    operation: str,
    rule: str,
) -> list[dict[str, Any]]:
    """Return a list of audit entries for cells that *meaningfully* changed.

    Skips semantic no-ops like '80' → 80.0 (pure type coercion) and
    None → None transitions. Only logs entries where the value actually
    changes in a way the user should know about.
    """
    entries = []
    changed_mask = before != after
    null_appeared = before.isna() & after.notna()
    null_disappeared = before.notna() & after.isna()
    mask = changed_mask | null_appeared | null_disappeared

    for idx in before.index[mask]:
        orig = before.at[idx]
        new = after.at[idx]
        # Skip semantic no-ops (e.g. "80" → 80.0)
        if _values_semantically_equal(orig, new):
            continue
        entries.append({
            "row": int(idx) + 1,          # 1-based for human readability
            "column": column,
            "original_value": None if pd.isna(orig) else orig,
            "new_value": None if pd.isna(new) else new,
            "operation": operation,
            "rule": rule,
        })
    return entries


# ---------------------------------------------------------------------------
# Cleaning step executors
# ---------------------------------------------------------------------------


def _clean_column_names(
    df: pd.DataFrame, column: str | None, params: dict, audit: list
) -> pd.DataFrame:
    """Normalise column names: replace NBSP with space, strip whitespace, collapse doubles."""
    rename_map = {}
    for col in df.columns:
        cleaned = col.replace("\xa0", " ").strip()
        # Collapse double spaces
        while "  " in cleaned:
            cleaned = cleaned.replace("  ", " ")
        if cleaned != col:
            rename_map[col] = cleaned
    if rename_map:
        df = df.rename(columns=rename_map)
        for old_name, new_name in rename_map.items():
            audit.append({
                "row": 0,
                "column": old_name,
                "original_value": old_name,
                "new_value": new_name,
                "operation": "clean_column_names",
                "rule": "Column name normalised (NBSP/whitespace removed)",
            })
    return df


def _drop_empty_columns(
    df: pd.DataFrame, column: str | None, params: dict, audit: list
) -> pd.DataFrame:
    """Drop columns that are 100% null."""
    empty_cols = [col for col in df.columns if df[col].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)
        for col_name in empty_cols:
            audit.append({
                "row": 0,
                "column": col_name,
                "original_value": "(entire column)",
                "new_value": "<dropped>",
                "operation": "drop_empty_columns",
                "rule": "Column dropped: 100% null values",
            })
    return df


def _drop_incomplete_responses(
    df: pd.DataFrame, column: str | None, params: dict, audit: list
) -> pd.DataFrame:
    """Drop rows where survey progress < threshold and not finished.

    Params:
        progress_column: column with progress % (default 'Progress')
        finished_column: column with finished flag (default 'Finished')
        min_progress: minimum progress to keep (default 100)
    """
    progress_col = params.get("progress_column", "Progress")
    finished_col = params.get("finished_column", "Finished")
    min_progress = params.get("min_progress", 100)

    if progress_col not in df.columns:
        return df

    prog = pd.to_numeric(df[progress_col], errors="coerce")

    if finished_col in df.columns:
        finished_vals = df[finished_col].astype(str).str.strip().str.lower()
        drop_mask = (prog < min_progress) & (~finished_vals.isin(["true", "1", "yes"]))
    else:
        drop_mask = prog < min_progress

    dropped_indices = df.index[drop_mask].tolist()
    if dropped_indices:
        for idx in dropped_indices:
            audit.append({
                "row": int(idx) + 1,
                "column": progress_col,
                "original_value": f"Progress={df.at[idx, progress_col]}",
                "new_value": "<dropped>",
                "operation": "drop_incomplete_responses",
                "rule": f"Row dropped: incomplete survey response (Progress < {min_progress})",
            })
        df = df.drop(index=dropped_indices).reset_index(drop=True)
    return df


def _cap_extreme_values(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Cap extreme values at a specified maximum, replacing with NaN.

    More direct than flag_extreme_outliers — specifically targets values above
    a hard ceiling. Used for obvious data entry errors like $1B hotel costs.

    Params:
        max_value: values above this are set to NaN (required)
    """
    if column not in df.columns:
        return df

    max_value = params.get("max_value")
    if max_value is None:
        logger.warning("cap_extreme_values called without 'max_value' param on '%s'", column)
        return df

    numeric_col = pd.to_numeric(df[column], errors="coerce")
    extreme_mask = numeric_col > max_value

    if not extreme_mask.any():
        return df

    before = df[column].copy()
    df = df.copy()
    df.loc[extreme_mask, column] = pd.NA
    audit.extend(_diff_column(before, df[column], column, "cap_extreme_values",
                              f"Rule 4.3: Value exceeds reasonable maximum ({max_value}), set to null"))
    logger.info("Capped %d extreme values in column '%s' (max=%s)", extreme_mask.sum(), column, max_value)
    return df


def _drop_rows(
    df: pd.DataFrame, column: str | None, params: dict, audit: list
) -> pd.DataFrame:
    """Drop specific rows by integer index (e.g. Qualtrics metadata header rows)."""
    indices = params.get("indices", [])
    if not indices:
        return df
    valid = [i for i in indices if i < len(df)]
    for idx in valid:
        original = df.iloc[idx].to_dict()
        audit.append({
            "row_id": idx,
            "column": "_row_",
            "original_value": str(original),
            "new_value": "<dropped>",
            "rule": "drop_rows",
        })
    if valid:
        df = df.drop(index=valid).reset_index(drop=True)
    return df


def _strip_whitespace(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    if column in df.columns and (df[column].dtype == object or pd.api.types.is_string_dtype(df[column])):
        before = df[column].copy()
        df = df.copy()
        df[column] = df[column].str.strip()
        audit.extend(_diff_column(before, df[column], column, "strip_whitespace",
                                  "Rule 1: Strip leading/trailing whitespace"))
    return df


def _remove_currency_symbols(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Strip currency symbols ($, €, £, ¥, ₹) from string values."""
    if column not in df.columns:
        return df
    before = df[column].copy()
    df = df.copy()
    df[column] = df[column].astype(str).str.replace(
        r"[$€£¥₹]", "", regex=True
    ).str.strip()
    # Restore actual nulls that became the string "nan"
    df[column] = df[column].replace("nan", pd.NA)
    audit.extend(_diff_column(before, df[column], column, "remove_currency_symbols",
                              "Rule 1.1: Delete currency symbols from values"))
    return df


def _extract_number(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Extract the first numeric value from mixed text/number strings."""
    if column not in df.columns:
        return df
    before = df[column].copy()
    df = df.copy()

    def _parse(val: Any) -> Any:
        if pd.isna(val):
            return val
        text = str(val)
        m = re.search(r"[-+]?\d+(?:[,\d]*)?(?:\.\d+)?", text)
        if m:
            raw = m.group(0).replace(",", "")
            try:
                return float(raw) if "." in raw else int(raw)
            except ValueError:
                return val
        return val

    df[column] = df[column].apply(_parse)
    audit.extend(_diff_column(before, df[column], column, "extract_number",
                              "Rule 1.2: Extract numerical value from text string"))
    return df


def _convert_number_words(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Convert written number words ('five', 'twenty') to digits."""
    if column not in df.columns:
        return df
    before = df[column].copy()
    df = df.copy()

    def _word_to_num(val: Any) -> Any:
        if pd.isna(val):
            return val
        text = str(val).strip().lower()
        # Try matching a single word number
        words = _NUMBER_WORD_PATTERN.findall(text)
        if not words:
            return val
        total = 0
        current = 0
        for word in words:
            n = _NUMBER_WORDS.get(word.lower(), 0)
            if n == 100:
                current = (current or 1) * 100
            elif n == 1000:
                total += (current or 1) * 1000
                current = 0
            else:
                current += n
        result = total + current
        return result

    df[column] = df[column].apply(_word_to_num)
    audit.extend(_diff_column(before, df[column], column, "convert_number_words",
                              "Rule 1.3: Convert number words to digits"))
    return df


def _convert_time_to_number(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Extract numeric value from time expressions like '2 hours', '3 days'."""
    if column not in df.columns:
        return df
    before = df[column].copy()
    df = df.copy()

    def _parse_time(val: Any) -> Any:
        if pd.isna(val):
            return val
        text = str(val)
        m = _TIME_PATTERN.search(text)
        if m:
            raw = m.group(1)
            try:
                return float(raw) if "." in raw else int(raw)
            except ValueError:
                return val
        return val

    df[column] = df[column].apply(_parse_time)
    audit.extend(_diff_column(before, df[column], column, "convert_time_to_number",
                              "Rule 1.4: Convert time expressions to numeric values"))
    return df


def _free_to_zero(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Convert 'Free' (case-insensitive) to numeric 0."""
    if column not in df.columns:
        return df
    before = df[column].copy()
    df = df.copy()
    mask = df[column].astype(str).str.strip().str.lower().str.startswith("free")
    # Convert column to object dtype so mixed str/int assignment works
    df[column] = df[column].astype(object)
    df.loc[mask, column] = 0
    audit.extend(_diff_column(before, df[column], column, "free_to_zero",
                              "Rule 2.1: 'Free' entry converted to numeric 0"))
    return df


_VAGUE_PATTERNS = re.compile(
    r"^(not\s+much|very\s+little|n/?a|none|nothing|idk|unclear|unknown|"
    r"not\s+sure|not\s+applicable|tbd|tbc|–|—|-|\.\.\.?)$",
    re.IGNORECASE,
)


def _remove_vague_entries(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Null out vague, unquantifiable entries."""
    if column not in df.columns:
        return df

    # Skip columns that are already fully numeric — they can't contain vague text
    if pd.api.types.is_numeric_dtype(df[column]):
        return df

    before = df[column].copy()
    df = df.copy()

    def _is_vague(val: Any) -> bool:
        if pd.isna(val):
            return False
        text = str(val).strip()
        return bool(_VAGUE_PATTERNS.match(text))

    mask = df[column].apply(_is_vague)
    df.loc[mask, column] = pd.NA
    audit.extend(_diff_column(before, df[column], column, "remove_vague_entries",
                              "Rule 2.2: Vague/unquantifiable entry removed (set to null)"))
    return df


def _sum_composite_expenses(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Parse composite expense strings and replace with the summed total.

    e.g. 'Hotel - $150, Gas $300, F&B $300' → 750
    """
    if column not in df.columns:
        return df
    before = df[column].copy()
    df = df.copy()

    def _sum_expenses(val: Any) -> Any:
        if pd.isna(val):
            return val
        text = str(val)
        # Only act if the cell contains multiple amounts or a composite-looking string
        amounts = _CURRENCY_AMOUNT_PATTERN.findall(text)
        if len(amounts) < 2:
            return val
        try:
            total = sum(float(a.replace(",", "")) for a in amounts)
            return int(total) if total == int(total) else total
        except (ValueError, TypeError):
            return val

    df[column] = df[column].apply(_sum_expenses)
    audit.extend(_diff_column(before, df[column], column, "sum_composite_expenses",
                              "Rule 3.1: Composite expense list extracted and summed"))
    return df


def _flag_extreme_outliers(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Null out extreme outlier values and mark affected rows with a flag column.

    Uses a modified Z-score (MAD-based) method which is robust to the outlier
    inflating the IQR. Values with |modified_z| > threshold are flagged.
    Falls back to 99th-percentile cutoff when MAD is zero.
    """
    if column not in df.columns:
        return df

    threshold = params.get("threshold", 5.0)   # modified Z-score threshold — 5.0 is forgiving enough for normal spend variation
    flag_col = params.get("flag_column", "_flagged")

    # Try to work with numeric values even if column is still object dtype
    # (e.g. after cap_extreme_values nulled some cells but before cast_type)
    if not pd.api.types.is_numeric_dtype(df[column]):
        coerced = pd.to_numeric(df[column], errors="coerce")
        if coerced.notna().sum() < 4:
            return df
        df = df.copy()
        df[column] = coerced

    numeric = pd.to_numeric(df[column], errors="coerce").dropna()
    if len(numeric) < 4:
        return df

    median_val = numeric.median()
    mad = (numeric - median_val).abs().median()

    if mad == 0:
        # Fallback: values above 99th percentile
        upper = numeric.quantile(0.99)
        extreme_mask = df[column].notna() & (df[column] > upper)
    else:
        modified_z = 0.6745 * (df[column] - median_val).abs() / mad
        extreme_mask = modified_z > threshold

    if not extreme_mask.any():
        return df

    upper = df.loc[extreme_mask, column].min()   # for audit message

    before = df[column].copy()
    df = df.copy()

    # Add flag column if it doesn't exist
    if flag_col not in df.columns:
        df[flag_col] = ""

    df.loc[extreme_mask, flag_col] = (
        df.loc[extreme_mask, flag_col].astype(str) + f"OUTLIER:{column} "
    ).str.strip()
    df.loc[extreme_mask, column] = pd.NA

    audit.extend(_diff_column(before, df[column], column, "flag_extreme_outliers",
                              f"Rule 4.1: Extreme outlier (≥{upper}) removed and row flagged for review"))
    logger.info("Flagged %d extreme outliers in column '%s'", extreme_mask.sum(), column)
    return df


def _flag_contextual_fraud(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    """Flag rows where a value is contextually suspicious (e.g. $300 parking).

    Params:
        threshold: numeric value above which the entry is suspicious
        flag_column: name of the flag column (default '_flagged')
        reason: human-readable fraud reason description
    """
    if column not in df.columns:
        return df

    threshold = params.get("threshold")
    flag_col = params.get("flag_column", "_flagged")
    reason = params.get("reason", f"Suspicious value in {column}")

    if threshold is None:
        logger.warning("flag_contextual_fraud called without 'threshold' param on '%s'", column)
        return df

    numeric_col = pd.to_numeric(df[column], errors="coerce")
    fraud_mask = numeric_col > threshold

    if not fraud_mask.any():
        return df

    df = df.copy()
    if flag_col not in df.columns:
        df[flag_col] = ""

    df.loc[fraud_mask, flag_col] = (
        df.loc[fraud_mask, flag_col].astype(str) + f"FRAUD:{reason} "
    ).str.strip()

    for idx in df.index[fraud_mask]:
        audit.append({
            "row": int(idx) + 1,
            "column": column,
            "original_value": df.at[idx, column],
            "new_value": df.at[idx, column],          # value kept, only flagged
            "operation": "flag_contextual_fraud",
            "rule": f"Rule 4.2: {reason} (threshold: {threshold})",
        })

    logger.info("Flagged %d rows for contextual fraud in column '%s'", fraud_mask.sum(), column)
    return df


def _fill_null(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    if column not in df.columns:
        return df

    strategy = params.get("strategy")
    value = params.get("value")
    before = df[column].copy()
    df = df.copy()

    if strategy:
        if strategy == "mean" and pd.api.types.is_numeric_dtype(df[column]):
            fill_val = df[column].mean()
        elif strategy == "median" and pd.api.types.is_numeric_dtype(df[column]):
            fill_val = df[column].median()
        elif strategy == "mode":
            mode_vals = df[column].mode()
            fill_val = mode_vals.iloc[0] if len(mode_vals) > 0 else None
        else:
            logger.warning("Unknown fill_null strategy '%s' for column '%s'", strategy, column)
            return df
        if fill_val is not None:
            df[column] = df[column].fillna(fill_val)
    elif value is not None:
        df[column] = df[column].fillna(value)

    audit.extend(_diff_column(before, df[column], column, "fill_null",
                              f"Null value filled (strategy={strategy or 'value'})"))
    return df


def _drop_null(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    if column in df.columns:
        dropped_indices = df.index[df[column].isna()].tolist()
        df = df.dropna(subset=[column]).reset_index(drop=True)
        for idx in dropped_indices:
            audit.append({
                "row": int(idx) + 1,
                "column": column,
                "original_value": None,
                "new_value": None,
                "operation": "drop_null",
                "rule": "Row dropped: null value in required column",
            })
    return df


def _cast_type(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    if column not in df.columns:
        return df

    target_type = params.get("target_type", "str")
    before = df[column].copy()
    df = df.copy()
    try:
        if target_type == "int":
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
        elif target_type == "float":
            df[column] = pd.to_numeric(df[column], errors="coerce")
        elif target_type == "datetime":
            df[column] = pd.to_datetime(df[column], errors="coerce")
        elif target_type == "str":
            df[column] = df[column].astype(str)
        else:
            logger.warning("Unknown target_type '%s' for cast_type", target_type)
            return df
    except Exception as exc:
        logger.warning("Failed to cast column '%s' to '%s': %s", column, target_type, exc)
        return df

    audit.extend(_diff_column(before, df[column], column, "cast_type",
                              f"Column cast to {target_type}"))
    return df


def _deduplicate(
    df: pd.DataFrame, column: str | None, params: dict, audit: list
) -> pd.DataFrame:
    subset = params.get("subset")
    if subset:
        dropped_indices = df.index[df.duplicated(subset=subset, keep="first")].tolist()
        df = df.drop_duplicates(subset=subset).reset_index(drop=True)
    else:
        dropped_indices = df.index[df.duplicated(keep="first")].tolist()
        df = df.drop_duplicates().reset_index(drop=True)
    for idx in dropped_indices:
        audit.append({
            "row": int(idx) + 1,
            "column": "(duplicate)",
            "original_value": None,
            "new_value": None,
            "operation": "deduplicate",
            "rule": "Row dropped: duplicate",
        })
    return df


def _rename_column(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    new_name = params.get("new_name")
    if column in df.columns and new_name:
        df = df.rename(columns={column: new_name})
    return df


def _standardize_values(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    mapping = params.get("mapping", {})
    if column in df.columns and mapping:
        before = df[column].copy()
        df = df.copy()
        df[column] = df[column].replace(mapping)
        audit.extend(_diff_column(before, df[column], column, "standardize_values",
                                  "Values standardized per mapping"))
    return df


def _remove_outliers(
    df: pd.DataFrame, column: str, params: dict, audit: list
) -> pd.DataFrame:
    if column not in df.columns or not pd.api.types.is_numeric_dtype(df[column]):
        return df

    q1 = df[column].quantile(0.25)
    q3 = df[column].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 3.0 * iqr
    upper = q3 + 3.0 * iqr
    out_mask = (df[column] < lower) | (df[column] > upper)
    dropped_indices = df.index[out_mask].tolist()
    df = df[(df[column] >= lower) & (df[column] <= upper)].reset_index(drop=True)
    for idx in dropped_indices:
        audit.append({
            "row": int(idx) + 1,
            "column": column,
            "original_value": None,
            "new_value": None,
            "operation": "remove_outliers",
            "rule": "Row dropped: IQR outlier",
        })
    return df


_OPERATION_MAP: dict[str, Any] = {
    # Structural cleanup (run first)
    "clean_column_names": _clean_column_names,
    "drop_empty_columns": _drop_empty_columns,
    "drop_incomplete_responses": _drop_incomplete_responses,
    # Row removal
    "drop_rows": _drop_rows,
    # Formatting & extraction
    "strip_whitespace": _strip_whitespace,
    "remove_currency_symbols": _remove_currency_symbols,
    "extract_number": _extract_number,
    "convert_number_words": _convert_number_words,
    "convert_time_to_number": _convert_time_to_number,
    # Standardization
    "free_to_zero": _free_to_zero,
    "remove_vague_entries": _remove_vague_entries,
    "fill_null": _fill_null,
    "drop_null": _drop_null,
    "cast_type": _cast_type,
    "standardize_values": _standardize_values,
    # Aggregation
    "sum_composite_expenses": _sum_composite_expenses,
    # Anomaly detection
    "flag_extreme_outliers": _flag_extreme_outliers,
    "flag_contextual_fraud": _flag_contextual_fraud,
    "cap_extreme_values": _cap_extreme_values,
    # Other
    "deduplicate": _deduplicate,
    "rename_column": _rename_column,
    "remove_outliers": _remove_outliers,
}


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------


def execute_cleaning_plan(
    df: pd.DataFrame,
    steps: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute an ordered list of cleaning steps on a DataFrame.

    Each step dict must have: operation, column, params, description.

    Returns:
        (cleaned_df, audit_log, failed_steps) where:
        - audit_log is a list of dicts:
          [{row, column, original_value, new_value, operation, rule}, ...]
        - failed_steps is a list of dicts for operations that raised exceptions:
          [{step_index, operation, column, error}, ...]
    """
    original_shape = df.shape
    audit_log: list[dict[str, Any]] = []
    failed_steps: list[dict[str, Any]] = []

    logger.info(
        "Executing cleaning plan with %d steps on DataFrame %s",
        len(steps), original_shape,
    )

    for i, step in enumerate(steps):
        operation = step.get("operation", "")
        column = step.get("column")
        params = step.get("params", {})
        description = step.get("description", "")

        executor = _OPERATION_MAP.get(operation)
        if executor is None:
            logger.warning("Skipping unknown operation '%s' at step %d", operation, i)
            failed_steps.append({
                "step_index": i,
                "operation": operation,
                "column": column,
                "error": f"Unknown operation '{operation}'",
            })
            continue

        try:
            before_shape = df.shape
            df = executor(df, column, params, audit_log)
            logger.info(
                "Step %d/%d [%s] on '%s': %s -> %s | %s",
                i + 1, len(steps), operation, column,
                before_shape, df.shape, description,
            )
        except Exception as exc:
            logger.error("Step %d/%d [%s] failed: %s", i + 1, len(steps), operation, exc)
            failed_steps.append({
                "step_index": i,
                "operation": operation,
                "column": column,
                "error": str(exc),
            })
            continue

    logger.info(
        "Cleaning complete: %s -> %s | %d cells modified | %d steps failed",
        original_shape, df.shape, len(audit_log), len(failed_steps),
    )
    return df, audit_log, failed_steps
