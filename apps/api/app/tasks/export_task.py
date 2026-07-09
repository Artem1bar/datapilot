"""Celery task: export a dataset to a requested file format.

Downloads the (cleaned) file from MinIO/R2, converts it using the export
service, uploads the result back to storage, and updates the job record.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound

from app.config import settings
from app.services.storage import download_file_bytes, get_s3_client
from app.tasks._errors import user_facing_error
from app.tasks.celery_app import celery_app
from app.utils.dataframe import read_dataframe

logger = logging.getLogger(__name__)


def _get_sync_engine():
    """Return the shared per-process sync engine (see app.tasks._db)."""
    from app.tasks._db import get_sync_engine

    return get_sync_engine()


def _publish_progress_sync(job_id: str, status: str, progress: int, message: str = "") -> None:
    """Report job progress (persists to the Job row + Redis pub/sub)."""
    from app.tasks._progress import publish_progress_sync

    publish_progress_sync(job_id, status, progress, message)


@celery_app.task(bind=True, name="export_dataset", max_retries=2)
def export_dataset(
    self,
    dataset_id: str,
    job_id: str,
    format: str,
    columns_json: str | None = None,
) -> dict:
    """Export a dataset to the requested format and upload to storage."""
    from sqlalchemy.orm import Session

    from app.models.dataset import Dataset
    from app.models.job import Job
    from app.services.export import (
        export_to_csv,
        export_to_json,
        export_to_parquet,
        export_to_xlsx,
    )

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

        # Try to download cleaned version first, fall back to original
        cleaned_key = dataset.r2_key.rsplit(".", 1)
        if len(cleaned_key) == 2:
            cleaned_r2_key = f"{cleaned_key[0]}_cleaned.{cleaned_key[1]}"
        else:
            cleaned_r2_key = f"{dataset.r2_key}_cleaned"

        try:
            file_bytes = download_file_bytes(cleaned_r2_key)
            logger.info("Using cleaned version for dataset %s", dataset_id)
        except Exception:
            file_bytes = download_file_bytes(dataset.r2_key)
            logger.info("Using original version for dataset %s", dataset_id)

        _publish_progress_sync(job_id, "running", 30, "Parsing file")

        # Parse the file
        df = read_dataframe(file_bytes, dataset.filename)
        _publish_progress_sync(job_id, "running", 50, f"Exporting to {format}")

        # Parse columns if provided
        columns: list[str] | None = None
        if columns_json is not None:
            columns = json.loads(columns_json)

        # Export to the requested format
        exporters = {
            "csv": export_to_csv,
            "xlsx": export_to_xlsx,
            "json": export_to_json,
            "parquet": export_to_parquet,
        }

        exporter = exporters.get(format)
        if exporter is None:
            raise ValueError(f"Unsupported export format: {format}")

        exported_bytes = exporter(df, columns=columns)
        _publish_progress_sync(job_id, "running", 70, "Uploading exported file")

        # Upload to MinIO/R2
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        export_key = f"exports/{dataset_id}/{timestamp}.{format}"

        s3 = get_s3_client()
        s3.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=export_key,
            Body=exported_bytes,
        )

        _publish_progress_sync(job_id, "running", 90, "Saving results")

        # Update job with result
        with Session(engine) as session:
            now = datetime.now(UTC)
            session.execute(
                update(Job)
                .where(Job.id == uuid.UUID(job_id))
                .values(
                    status="completed",
                    progress=100,
                    result_json={"r2_key": export_key},
                    completed_at=now,
                )
            )
            session.commit()

        _publish_progress_sync(job_id, "completed", 100, "Export complete")
        logger.info("Exported dataset %s to %s successfully", dataset_id, format)
        return {"status": "completed", "dataset_id": dataset_id, "job_id": job_id}

    except Exception as exc:
        logger.exception("Failed to export dataset %s", dataset_id)

        non_retryable = isinstance(exc, (ValueError, TypeError, KeyError, NoResultFound))
        retries_exhausted = (self.request.retries or 0) >= self.max_retries
        if not (non_retryable or retries_exhausted):
            # Transient failure with retries left: keep the job in "running"
            # state so clients don't see a failure that may still succeed.
            _publish_progress_sync(job_id, "running", 0, f"Transient error — retrying: {exc}")
            raise self.retry(exc=exc, countdown=30)

        error_message = user_facing_error(exc)
        _publish_progress_sync(job_id, "failed", 0, error_message)

        with Session(engine) as session:
            session.execute(
                update(Job)
                .where(Job.id == uuid.UUID(job_id))
                .values(
                    status="failed",
                    error_text=error_message,
                    completed_at=datetime.now(UTC),
                )
            )
            session.commit()

        raise
