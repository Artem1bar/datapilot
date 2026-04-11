"""Celery task: apply a cleaning plan to a dataset.

Downloads the file from MinIO/R2, executes cleaning steps via pandas,
uploads the cleaned file back, and updates DB records.
"""

from __future__ import annotations

import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select, update

from app.tasks.celery_app import celery_app
from app.config import settings
from app.services.storage import download_file_bytes, get_s3_client

logger = logging.getLogger(__name__)


def _get_sync_engine():
    """Create a synchronous SQLAlchemy engine for use inside Celery workers."""
    from sqlalchemy import create_engine

    if "asyncpg" in settings.DATABASE_URL:
        sync_url = settings.DATABASE_URL.replace("asyncpg", "psycopg2")
    else:
        sync_url = settings.DATABASE_URL
    return create_engine(sync_url)


def _publish_progress_sync(job_id: str, status: str, progress: int, message: str = "") -> None:
    """Publish job progress via Redis (synchronous)."""
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
        return pd.read_csv(io.BytesIO(file_bytes))


def _dataframe_to_bytes(
    df: pd.DataFrame,
    filename: str,
    audit_log: list[dict] | None = None,
) -> tuple[bytes, str]:
    """Serialize a DataFrame to bytes based on the file extension.

    For Excel output, appends a 'Cleaning Legend' sheet when an audit_log
    is provided.

    Returns (file_bytes, content_type).
    """
    lower = filename.lower()
    buf = io.BytesIO()

    if lower.endswith((".xls", ".xlsx")):
        from openpyxl.comments import Comment

        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Cleaned Data", index=False)

            if audit_log:
                # ── Add cell comments to every edited cell ──
                # Only record the FIRST (pre-cleaning) original value per cell
                # so multi-step operations show the true original, not an intermediate.
                ws = writer.sheets["Cleaned Data"]
                col_names = list(df.columns)
                first_orig: dict[tuple, str] = {}
                for entry in audit_log:
                    col_name = entry.get("column")
                    row_num = entry.get("row")  # 1-based row in data
                    orig = entry.get("original_value")
                    if col_name is None or row_num is None:
                        continue
                    if col_name == "_row_":
                        continue  # skip dropped-row entries
                    key = (row_num, col_name)
                    if key not in first_orig:
                        first_orig[key] = "" if orig is None else str(orig)

                for (row_num, col_name), orig_display in first_orig.items():
                    if col_name not in col_names:
                        continue
                    col_idx = col_names.index(col_name) + 1  # 1-based
                    excel_row = row_num + 1  # +1 for header row
                    try:
                        cell = ws.cell(row=excel_row, column=col_idx)
                        cell.comment = Comment(
                            f'WAS: "{orig_display}"',
                            "DataPilot",
                        )
                    except Exception:
                        pass  # skip if cell out of range

                # ── Cleaning Legend sheet ──
                legend_df = pd.DataFrame(audit_log, columns=[
                    "row", "column", "original_value", "new_value",
                    "operation", "rule",
                ])
                legend_df.columns = [
                    "Row", "Column", "Original Value", "New Value",
                    "Operation", "Rule Applied",
                ]
                legend_df.to_excel(writer, sheet_name="Cleaning Legend", index=False)

        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif lower.endswith(".parquet"):
        df.to_parquet(buf, index=False)
        content_type = "application/octet-stream"
    elif lower.endswith(".json"):
        df.to_json(buf, orient="records", indent=2)
        content_type = "application/json"
    elif lower.endswith((".tsv", ".tab")):
        df.to_csv(buf, index=False, sep="\t")
        content_type = "text/tab-separated-values"
    else:
        # Default to CSV — append audit log as a separate section
        df.to_csv(buf, index=False)
        if audit_log:
            buf.write(b"\n\n# Cleaning Legend\n")
            legend_df = pd.DataFrame(audit_log)
            legend_df.to_csv(buf, index=False)
        content_type = "text/csv"

    buf.seek(0)
    return buf.read(), content_type


def _make_cleaned_key(r2_key: str) -> str:
    """Derive a cleaned file key by adding _cleaned before the extension."""
    base, ext = os.path.splitext(r2_key)
    return f"{base}_cleaned{ext}"


@celery_app.task(bind=True, name="clean_dataset", max_retries=2)
def clean_dataset(self, dataset_id: str, job_id: str, steps_json: str) -> dict:
    """Download a dataset, apply cleaning steps, and upload the cleaned result."""
    from sqlalchemy.orm import Session
    from app.models.dataset import Dataset
    from app.models.job import Job

    engine = _get_sync_engine()

    try:
        _publish_progress_sync(job_id, "running", 5, "Starting cleaning task")

        # Mark job as running
        with Session(engine) as session:
            session.execute(
                update(Job).where(Job.id == uuid.UUID(job_id)).values(status="running", progress=5)
            )
            session.commit()

            # Fetch dataset info
            result = session.execute(select(Dataset).where(Dataset.id == uuid.UUID(dataset_id)))
            dataset = result.scalar_one()
            r2_key = dataset.r2_key
            filename = dataset.filename

        # Download file
        _publish_progress_sync(job_id, "running", 10, "Downloading file from storage")
        file_bytes = download_file_bytes(r2_key)

        # Validate file content matches extension
        from app.utils.file_validation import validate_file_content

        if not validate_file_content(file_bytes, filename):
            raise ValueError(
                f"File content does not match expected format for '{filename}'. "
                "The file may be corrupted or have the wrong extension."
            )

        # Parse into DataFrame
        _publish_progress_sync(job_id, "running", 20, "Parsing file")
        df = _read_dataframe(file_bytes, filename)
        original_df = df.copy()
        original_rows = len(df)

        # Fetch original quality flags from dataset profile
        original_quality_flags: dict[str, Any] = {}
        with Session(engine) as session:
            ds_result = session.execute(
                select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
            )
            ds = ds_result.scalar_one()
            if ds.profile_json and "data_quality" in ds.profile_json:
                original_quality_flags = ds.profile_json["data_quality"]

        # Parse cleaning steps
        steps = json.loads(steps_json)
        _publish_progress_sync(job_id, "running", 30, f"Executing {len(steps)} cleaning steps")

        # Execute cleaning plan
        from app.services.cleaning import execute_cleaning_plan

        df, audit_log, failed_steps = execute_cleaning_plan(df, steps)

        if failed_steps:
            logger.warning(
                "Dataset %s: %d/%d cleaning steps failed: %s",
                dataset_id, len(failed_steps), len(steps),
                [s["operation"] for s in failed_steps],
            )

        # --- Verification + remediation loop (max 2 rounds) ---
        # Keep tight to avoid rate limit exhaustion and frontend timeouts.
        MAX_REMEDIATION_ROUNDS = 2
        all_remediation_steps: list[dict] = []
        agent_assessment = None

        for round_num in range(MAX_REMEDIATION_ROUNDS):
            round_label = f"Round {round_num + 1}/{MAX_REMEDIATION_ROUNDS}"

            # Progress: spread rounds across 55–85%
            progress_base = 55 + round_num * 6

            _publish_progress_sync(
                job_id, "running",
                progress_base,
                f"Verifying cleaning results ({round_label})",
            )

            from app.services.verification import verify_cleaning_result

            verification_report = verify_cleaning_result(
                original_df=original_df,
                cleaned_df=df,
                steps=steps + all_remediation_steps,
                audit_log=audit_log,
                original_quality_flags=original_quality_flags,
                failed_steps=failed_steps,
            )

            verification_data = verification_report.to_dict()
            verification_data.pop("flags_before", None)
            verification_data.pop("flags_after", None)

            # If deterministic check passes cleanly AND no failed steps, we're done
            if (
                verification_report.overall_passed
                and verification_report.audit_completeness >= 0.9
                and not failed_steps
            ):
                logger.info("Verification passed on %s — no remediation needed", round_label)
                break

            # Run Claude verification agent
            _publish_progress_sync(
                job_id, "running",
                progress_base + 2,
                f"Running AI verification agent ({round_label})",
            )

            try:
                from app.services.verification_agent import run_verification_agent

                # Send ALL rows for small datasets, up to 100 for larger ones
                sample_size = min(len(df), 100)
                cleaned_sample = df.head(sample_size).to_dict(orient="records")
                agent_result = run_verification_agent(
                    original_quality_flags=original_quality_flags,
                    steps_applied=steps + all_remediation_steps,
                    audit_log_sample=audit_log[:300],
                    cleaned_sample_rows=cleaned_sample,
                    deterministic_report=verification_data,
                )
                agent_assessment = agent_result.to_dict()

                # Count critical/high issues
                critical_high = [
                    i for i in agent_result.issues_found
                    if isinstance(i, dict) and i.get("severity") in ("CRITICAL", "HIGH")
                ]

                logger.info(
                    "Verification agent (%s): passed=%s confidence=%.2f "
                    "issues=%d (critical/high=%d) remediation_steps=%d",
                    round_label, agent_result.passed, agent_result.confidence,
                    len(agent_result.issues_found), len(critical_high),
                    len(agent_result.remediation_steps),
                )

                # Only stop if agent says passed AND no critical/high issues remain
                if agent_result.passed and not critical_high:
                    agent_assessment["remediation_applied"] = bool(all_remediation_steps)
                    break

                # If agent found issues but gave no remediation steps, stop (can't fix)
                if not agent_result.remediation_steps:
                    logger.warning(
                        "Agent found %d issues but gave no remediation steps in %s — stopping",
                        len(agent_result.issues_found), round_label,
                    )
                    agent_assessment["remediation_applied"] = bool(all_remediation_steps)
                    break

                # Apply remediation steps
                remediation_steps = list(agent_result.remediation_steps)
                _publish_progress_sync(
                    job_id, "running",
                    progress_base + 4,
                    f"Applying {len(remediation_steps)} remediation step(s) ({round_label})",
                )
                logger.info(
                    "Applying %d remediation step(s) in %s: %s",
                    len(remediation_steps), round_label,
                    [s.get("operation") for s in remediation_steps],
                )

                from app.services.cleaning import execute_cleaning_plan

                df, extra_audit, extra_failed = execute_cleaning_plan(df, remediation_steps)
                audit_log = audit_log + extra_audit
                all_remediation_steps.extend(remediation_steps)
                if extra_failed:
                    failed_steps = failed_steps + extra_failed
                    logger.warning(
                        "%d remediation step(s) failed in %s: %s",
                        len(extra_failed), round_label,
                        [s.get("operation") for s in extra_failed],
                    )

                agent_assessment["remediation_applied"] = True
                agent_assessment["remediation_round"] = round_num + 1
                agent_assessment["remediation_steps_count"] = len(all_remediation_steps)

            except Exception as agent_exc:
                logger.exception("Verification agent failed in %s: %s", round_label, agent_exc)
                agent_assessment = {"error": f"Verification agent unavailable ({round_label})"}
                break
        else:
            # Loop exhausted without passing — run final verification
            logger.warning(
                "Remediation loop exhausted after %d rounds without passing",
                MAX_REMEDIATION_ROUNDS,
            )

        # Final verification snapshot after all remediation
        if all_remediation_steps:
            _publish_progress_sync(job_id, "running", 80, "Final verification after remediation")
            final_report = verify_cleaning_result(
                original_df=original_df,
                cleaned_df=df,
                steps=steps + all_remediation_steps,
                audit_log=audit_log,
                original_quality_flags=original_quality_flags,
                failed_steps=failed_steps,
            )
            verification_data = final_report.to_dict()
            verification_data.pop("flags_before", None)
            verification_data.pop("flags_after", None)

            if agent_assessment:
                agent_assessment["post_remediation_passed"] = final_report.overall_passed
                agent_assessment["total_remediation_rounds"] = len(all_remediation_steps)

        verification_data["agent_assessment"] = agent_assessment

        # Update cleaned_rows AFTER all remediation
        cleaned_rows = len(df)

        _publish_progress_sync(job_id, "running", 80, "Uploading cleaned file")

        # Serialize and upload cleaned file (with Cleaning Legend for Excel)
        cleaned_key = _make_cleaned_key(r2_key)
        output_bytes, content_type = _dataframe_to_bytes(df, filename, audit_log)

        client = get_s3_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=cleaned_key,
            Body=output_bytes,
            ContentType=content_type,
        )

        _publish_progress_sync(job_id, "running", 90, "Updating database records")

        # Update DB
        result_data = {
            "cleaned_r2_key": cleaned_key,
            "original_rows": original_rows,
            "cleaned_rows": cleaned_rows,
            "rows_removed": original_rows - cleaned_rows,
            "steps_applied": len(steps),
            "steps_failed": len(failed_steps),
            "cells_modified": len(audit_log),
            "audit_log": audit_log,          # full Cleaning Legend
            "failed_steps": failed_steps,
            "verification": verification_data,
        }

        with Session(engine) as session:
            now = datetime.now(timezone.utc)

            session.execute(
                update(Job)
                .where(Job.id == uuid.UUID(job_id))
                .values(
                    status="completed",
                    progress=100,
                    result_json=result_data,
                    completed_at=now,
                )
            )
            session.commit()

        _publish_progress_sync(job_id, "completed", 100, "Cleaning complete")
        logger.info(
            "Cleaned dataset %s: %d -> %d rows (%d steps)",
            dataset_id, original_rows, cleaned_rows, len(steps),
        )
        return {"status": "completed", "dataset_id": dataset_id, "job_id": job_id}

    except Exception as exc:
        logger.exception("Failed to clean dataset %s", dataset_id)
        _publish_progress_sync(job_id, "failed", 0, str(exc))

        with Session(engine) as session:
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
