"""Celery task: profile a dataset after upload.

Downloads the file from MinIO/R2, parses it with pandas, computes basic
statistics, and writes the profile back to the database.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd


def _to_python(obj):
    """Recursively convert numpy/pandas/datetime types to plain Python for JSON safety."""
    from datetime import date, datetime as dt
    if isinstance(obj, dict):
        return {k: _to_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_python(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [_to_python(v) for v in obj.tolist()]
    if isinstance(obj, (dt, date)):
        return obj.isoformat()
    if hasattr(obj, 'item'):  # catches remaining numpy scalars
        return obj.item()
    return obj
from sqlalchemy import select, update

from app.tasks.celery_app import celery_app
from app.config import settings
from app.services.storage import download_file_bytes

logger = logging.getLogger(__name__)


def _get_sync_engine():
    """Create a synchronous SQLAlchemy engine for use inside Celery workers."""
    from sqlalchemy import create_engine

    # If the URL uses asyncpg, swap it; otherwise use as-is
    if "asyncpg" in settings.DATABASE_URL:
        sync_url = settings.DATABASE_URL.replace("asyncpg", "psycopg2")
    else:
        sync_url = settings.DATABASE_URL
    return create_engine(sync_url)


def _publish_progress_sync(job_id: str, status: str, progress: int, message: str = "") -> None:
    """Publish job progress via Redis (synchronous)."""
    import json
    import redis

    try:
        r = redis.from_url(settings.REDIS_URL)
        payload = json.dumps({
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "message": message,
            "result": None,
        })
        r.publish(f"job:{job_id}:progress", payload)
        r.close()
    except Exception as exc:
        logger.warning("Progress publish failed (non-fatal): %s", exc)


def detect_quality_issues(df: pd.DataFrame) -> dict:
    """Scan each column for common data-quality problems and return a flags dict."""
    import re as _re

    NUMBER_WORDS = {
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "twenty", "thirty", "forty", "fifty",
        "hundred", "thousand",
    }
    VAGUE_WORDS = {"n/a", "na", "not much", "very little", "nothing", "none", "unknown"}

    # Column-name patterns that signal numeric/cost fields worth cleaning
    _NUMERIC_PATTERNS = _re.compile(
        r"(exp(end|ense)?|cost|fare|spend|price|amount|total|rate|fee|night|person|group|count|number|nights?|persons?)",
        _re.IGNORECASE,
    )
    # Column-name patterns that signal ID / text / categorical fields → skip numeric cleaning
    # NOTE: use \b word boundaries so "end" doesn't match inside "Expend", "spend", etc.
    _SKIP_NUMERIC_PATTERNS = _re.compile(
        r"(id$|_id|\bname\b|email|raffle|latitude|longitude|\blat\b|\blon\b|zip|ipaddr|\bip\b|"
        r"\bdate\b|channel|language|country|origin|income|range|\btext\b|events?[0-9_]|"
        r"response.*id|recipient|external|distribution|\bstatus\b|\btype\b|\blocation\b|"
        r"visitorzipcode|opt.*rec|race|gender|finished|recorded|\bstart\b|\bend\b|"
        r"\bduration\b|\bprogress\b|\bunder\s*18\b|\buser.?lang)",
        _re.IGNORECASE,
    )

    def _is_numeric_col(col_name: str) -> bool:
        """Heuristic: does this column name suggest it should contain numeric values?"""
        if _SKIP_NUMERIC_PATTERNS.search(col_name):
            return False
        return bool(_NUMERIC_PATTERNS.search(col_name))

    def _is_mostly_short(vals: "pd.Series") -> bool:  # noqa: F821
        """True if most values are short strings (< 30 chars) — likely amounts, not paragraphs."""
        return float(vals.str.len().median()) < 30

    flags: dict = {}

    # ── Non-breaking spaces / trailing whitespace in column names ──
    dirty_col_names = [
        col for col in df.columns
        if col != col.strip() or "\xa0" in str(col) or "  " in str(col)
    ]
    if dirty_col_names:
        flags["_dirty_column_names"] = {
            "columns": dirty_col_names,
            "description": (
                "Column names contain non-breaking spaces (\\xa0), trailing spaces, "
                "or double spaces. Use `clean_column_names` to normalise them."
            ),
        }

    # ── Completely empty columns (100% null) ──
    empty_cols = [col for col in df.columns if df[col].isna().all()]
    if empty_cols:
        flags["_empty_columns"] = {
            "columns": empty_cols,
            "description": (
                f"{len(empty_cols)} column(s) are entirely null/empty. "
                "Use `drop_empty_columns` to remove them."
            ),
        }

    # ── Incomplete survey responses (Progress < 100 AND Finished != True) ──
    if "Progress" in df.columns:
        prog = pd.to_numeric(df["Progress"], errors="coerce")
        finished_col = None
        for c in ("Finished", "finished", "FINISHED"):
            if c in df.columns:
                finished_col = c
                break
        if finished_col is not None:
            finished_vals = df[finished_col].astype(str).str.strip().str.lower()
            incomplete_mask = (prog < 100) & (~finished_vals.isin(["true", "1", "yes"]))
        else:
            incomplete_mask = prog < 100
        incomplete_count = int(incomplete_mask.sum())
        if incomplete_count > 0:
            flags["_incomplete_responses"] = {
                "count": incomplete_count,
                "indices": df.index[incomplete_mask].tolist()[:20],  # first 20
                "description": (
                    f"{incomplete_count} row(s) have Progress < 100 and are not marked Finished. "
                    "These are incomplete survey responses. Use `drop_incomplete_responses`."
                ),
            }

    # Qualtrics survey-export detection: first data row contains full question text
    if len(df) > 0:
        first = df.iloc[0]
        long_str_count = sum(
            1 for v in first
            if isinstance(v, str) and len(v) > 40
        )
        if long_str_count >= max(3, len(df.columns) * 0.25):
            flags["qualtrics_header_row"] = {
                "row_index": 0,
                "description": (
                    "First data row appears to be a Qualtrics/survey metadata row "
                    "containing full question descriptions, not actual data."
                ),
            }

    for col in df.columns:
        series = df[col].dropna()
        if len(series) == 0:
            continue
        str_vals = series.astype(str)
        col_flags: dict = {}
        is_numeric_col = _is_numeric_col(col)

        # --- Only flag numeric-cleaning issues on columns that SHOULD be cleaned ---
        # Skip system/metadata columns even if they happen to be numeric dtype
        is_skip_col = _SKIP_NUMERIC_PATTERNS.search(col)
        if (is_numeric_col or pd.api.types.is_numeric_dtype(series)) and not is_skip_col:

            # Currency symbols ($, €, £, ¥)
            currency_mask = str_vals.str.contains(r"[\$€£¥]", regex=True, na=False)
            if currency_mask.any() and _is_mostly_short(str_vals):
                col_flags["has_currency"] = True
                col_flags["currency_examples"] = str_vals[currency_mask].head(4).tolist()

            # "Free" / "free" values (e.g. "Free (comp by team)")
            free_mask = str_vals.str.lower().str.strip().str.startswith("free")
            if free_mask.any():
                col_flags["has_free_values"] = True
                col_flags["free_examples"] = str_vals[free_mask].head(3).tolist()

            # Embedded text mixed with numbers ("1.5 hours", "$400 a person", "20$")
            mixed_mask = str_vals.str.contains(
                r"(?:\d+[\.\d]*\s*[a-zA-Z]+|[a-zA-Z]+\s*\d+[\.\d]*)", regex=True, na=False
            )
            if mixed_mask.any():
                examples = [e for e in str_vals[mixed_mask].head(6).tolist() if len(e) < 35]
                if examples:
                    col_flags["has_embedded_text"] = True
                    col_flags["embedded_text_examples"] = examples[:4]

            # Extreme numeric outliers — use 15× IQR fence (forgiving), or mean+8*std when IQR=0
            numeric_coerced = pd.to_numeric(
                str_vals.str.replace(r"[^\d\.\-]", "", regex=True), errors="coerce"
            ).dropna()
            if len(numeric_coerced) >= 5:
                q25, q75 = numeric_coerced.quantile(0.25), numeric_coerced.quantile(0.75)
                iqr = q75 - q25
                if iqr > 0:
                    fence = q75 + 15 * iqr
                else:
                    # IQR=0 (e.g. mostly zeros): use mean + 8*std as fallback
                    mean, std = numeric_coerced.mean(), numeric_coerced.std()
                    fence = mean + 8 * std if std > 0 else float("inf")
                extremes = numeric_coerced[numeric_coerced > fence]
                if len(extremes) > 0:
                    col_flags["has_extreme_outliers"] = True
                    col_flags["extreme_values"] = extremes.head(3).tolist()

        # --- Number words apply to any column (e.g., Under18Group: "One", "Two") ---
        lower_vals = str_vals.str.lower().str.strip()
        word_mask = lower_vals.isin(NUMBER_WORDS)
        if word_mask.any():
            col_flags["has_number_words"] = True
            col_flags["number_word_examples"] = str_vals[word_mask].head(3).tolist()

        # --- Vague values apply to numeric-ish columns only ---
        if is_numeric_col:
            vague_mask = lower_vals.str.rstrip().isin(VAGUE_WORDS)
            if vague_mask.any():
                col_flags["has_vague_values"] = True
                col_flags["vague_examples"] = str_vals[vague_mask].head(3).tolist()

        if col_flags:
            flags[col] = col_flags

    return flags


def generate_smart_suggestions(df: pd.DataFrame, profile: dict) -> dict:
    """Generate smart suggestions for column operations."""
    import re
    suggestions = {
        "drop_candidates": [],      # columns that should be dropped
        "type_conversions": [],     # columns that need type changes
        "standardization": [],      # columns with inconsistent values
        "pii_detected": [],         # columns that may contain PII
    }

    for col in df.columns:
        series = df[col]
        col_profile = profile.get("columns", {}).get(col, {})

        # Drop candidates: 100% null, all same value, or system ID columns
        if col_profile.get("null_pct", 0) == 100:
            suggestions["drop_candidates"].append({
                "column": col, "reason": "100% null values", "confidence": 1.0
            })
        elif col_profile.get("unique_count", 0) == 1 and len(series.dropna()) > 1:
            suggestions["drop_candidates"].append({
                "column": col, "reason": "Constant value (all identical)", "confidence": 0.9
            })
        elif re.match(r"^(id|_id|.*_id|response_?id|recipient_?id|external_?ref|ip_?addr|ip_?address)$", col, re.I):
            suggestions["drop_candidates"].append({
                "column": col, "reason": "System/metadata ID column", "confidence": 0.7
            })

        # Type conversions: strings that look like dates or numbers
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            non_null = series.dropna()
            if len(non_null) == 0:
                continue
            sample = non_null.head(50)

            # Check for date-like strings
            date_count = 0
            for val in sample:
                try:
                    pd.to_datetime(str(val))
                    date_count += 1
                except (ValueError, TypeError):
                    pass
            if date_count > len(sample) * 0.8:
                suggestions["type_conversions"].append({
                    "column": col, "current_type": str(series.dtype),
                    "suggested_type": "datetime",
                    "examples": non_null.head(3).tolist(),
                    "confidence": round(date_count / len(sample), 2),
                })
                continue

            # Check for number-like strings
            numeric_count = pd.to_numeric(non_null.head(50), errors="coerce").notna().sum()
            if numeric_count > len(sample) * 0.8:
                suggestions["type_conversions"].append({
                    "column": col, "current_type": str(series.dtype),
                    "suggested_type": "numeric",
                    "examples": non_null.head(3).tolist(),
                    "confidence": round(numeric_count / len(sample), 2),
                })
                continue

            # Standardization: check for variant values
            if 2 <= col_profile.get("unique_count", 0) <= 50:
                top_values = col_profile.get("top_values", {})
                if top_values:
                    # Group similar values (case-insensitive comparison)
                    groups = {}
                    for val in top_values:
                        key = str(val).strip().lower()
                        if key not in groups:
                            groups[key] = []
                        groups[key].append(val)
                    variants = {k: v for k, v in groups.items() if len(v) > 1}
                    if variants:
                        suggestions["standardization"].append({
                            "column": col,
                            "variants": dict(list(variants.items())[:5]),
                            "unique_count": col_profile.get("unique_count", 0),
                        })

            # PII detection
            pii_patterns = {
                "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                "phone": r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
                "ssn": r"\b\d{3}[-]?\d{2}[-]?\d{4}\b",
                "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
            }
            text_sample = non_null.head(20).astype(str)
            for pii_type, pattern in pii_patterns.items():
                matches = text_sample.str.match(pattern, na=False).sum()
                if matches > len(text_sample) * 0.5:
                    suggestions["pii_detected"].append({
                        "column": col, "pii_type": pii_type,
                        "match_pct": round(matches / len(text_sample) * 100, 1),
                    })
                    break

    return suggestions


def _compute_profile(df: pd.DataFrame) -> dict:
    """Compute a basic statistical profile of a DataFrame."""
    profile: dict = {
        "row_count": len(df),
        "col_count": len(df.columns),
        "columns": {},
    }

    for col in df.columns:
        series = df[col]
        col_info: dict = {
            "dtype": str(series.dtype),
            "null_count": int(series.isna().sum()),
            "null_pct": round(float(series.isna().mean()) * 100, 2),
            "unique_count": int(series.nunique()),
        }

        if pd.api.types.is_numeric_dtype(series):
            desc = series.describe()
            col_info.update({
                "mean": round(float(desc.get("mean", 0)), 4),
                "std": round(float(desc.get("std", 0)), 4),
                "min": float(desc.get("min", 0)),
                "max": float(desc.get("max", 0)),
                "median": round(float(series.median()), 4),
                "q25": float(desc.get("25%", 0)),
                "q75": float(desc.get("75%", 0)),
            })
        elif pd.api.types.is_string_dtype(series) or pd.api.types.is_object_dtype(series):
            top_values = series.value_counts().head(10)
            col_info["top_values"] = {
                str(k): int(v) for k, v in top_values.items()
            }
            lengths = series.dropna().astype(str).str.len()
            if len(lengths) > 0:
                col_info["avg_length"] = round(float(lengths.mean()), 2)
                col_info["max_length"] = int(lengths.max())
        elif pd.api.types.is_datetime64_any_dtype(series):
            non_null = series.dropna()
            if len(non_null) > 0:
                col_info["min_date"] = str(non_null.min())
                col_info["max_date"] = str(non_null.max())

        profile["columns"][col] = col_info

    # Attach auto-detected quality flags so the AI cleaning step can act on them
    quality_issues = detect_quality_issues(df)
    if quality_issues:
        profile["data_quality"] = quality_issues

    profile["suggestions"] = generate_smart_suggestions(df, profile)

    return _to_python(profile)


def _read_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Read bytes into a pandas DataFrame based on file extension."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    elif lower.endswith((".xls", ".xlsx")):
        return pd.read_excel(io.BytesIO(file_bytes))
    elif lower.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(file_bytes))
    elif lower.endswith(".json"):
        return pd.read_json(io.BytesIO(file_bytes))
    elif lower.endswith((".tsv", ".tab")):
        return pd.read_csv(io.BytesIO(file_bytes), sep="\t")
    else:
        # Default to CSV
        return pd.read_csv(io.BytesIO(file_bytes))


@celery_app.task(bind=True, name="profile_dataset", max_retries=2)
def profile_dataset(self, dataset_id: str, job_id: str) -> dict:
    """Download a dataset from MinIO, profile it, and store results in the DB."""
    from sqlalchemy.orm import Session
    from app.models.dataset import Dataset
    from app.models.job import Job

    engine = _get_sync_engine()

    try:
        _publish_progress_sync(job_id, "running", 10, "Downloading file from storage")

        # Update job status to running
        with Session(engine) as session:
            session.execute(
                update(Job).where(Job.id == uuid.UUID(job_id)).values(status="running", progress=10)
            )
            session.commit()

            # Fetch dataset info
            result = session.execute(select(Dataset).where(Dataset.id == uuid.UUID(dataset_id)))
            dataset = result.scalar_one()

        # Download the file
        file_bytes = download_file_bytes(dataset.r2_key)
        _publish_progress_sync(job_id, "running", 30, "Parsing file")

        # Parse
        df = _read_dataframe(file_bytes, dataset.filename)
        _publish_progress_sync(job_id, "running", 50, "Computing statistics")

        # Profile
        profile = _compute_profile(df)
        _publish_progress_sync(job_id, "running", 80, "Saving results")

        # Get sheet names for Excel files
        sheet_names: list[str] | None = None
        if dataset.filename.lower().endswith((".xls", ".xlsx")):
            try:
                xls = pd.ExcelFile(io.BytesIO(file_bytes))
                sheet_names = xls.sheet_names
            except Exception:
                pass

        # Write results back
        with Session(engine) as session:
            now = datetime.now(timezone.utc)

            session.execute(
                update(Dataset)
                .where(Dataset.id == uuid.UUID(dataset_id))
                .values(
                    status="ready",
                    row_count=profile["row_count"],
                    col_count=profile["col_count"],
                    profile_json=profile,
                    sheet_names=sheet_names,
                )
            )
            session.execute(
                update(Job)
                .where(Job.id == uuid.UUID(job_id))
                .values(
                    status="completed",
                    progress=100,
                    result_json=profile,
                    completed_at=now,
                )
            )
            session.commit()

        _publish_progress_sync(job_id, "completed", 100, "Profiling complete")
        logger.info("Profiled dataset %s successfully", dataset_id)
        return {"status": "completed", "dataset_id": dataset_id, "job_id": job_id}

    except Exception as exc:
        logger.exception("Failed to profile dataset %s", dataset_id)
        _publish_progress_sync(job_id, "failed", 0, str(exc))

        with Session(engine) as session:
            session.execute(
                update(Dataset).where(Dataset.id == uuid.UUID(dataset_id)).values(status="error")
            )
            session.execute(
                update(Job)
                .where(Job.id == uuid.UUID(job_id))
                .values(
                    status="failed",
                    error_text=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

        raise self.retry(exc=exc, countdown=30)
