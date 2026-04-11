"""Celery task: export a dataset to a requested file format.

Downloads the (cleaned) file from MinIO/R2, converts it using the export
service, uploads the result back to storage, and updates the job record.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone

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
            source_key = cleaned_r2_key
            logger.info("Using cleaned version for dataset %s", dataset_id)
        except Exception:
            file_bytes = download_file_bytes(dataset.r2_key)
            source_key = dataset.r2_key
            logger.info("Using original version for dataset %s", dataset_id)

        _publish_progress_sync(job_id, "running", 30, "Parsing file")

        # Parse the file
        df = _read_dataframe(file_bytes, dataset.filename)
        _publish_progress_sync(job_id, "running", 50, "Exporting to %s" % format)

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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
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
            now = datetime.now(timezone.utc)
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
