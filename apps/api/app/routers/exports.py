"""Export endpoints."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.dataset import Dataset
from app.models.job import Job
from app.schemas import ExportRequest, JobResponse
from app.services.storage import create_presigned_download_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["exports"])


@router.post("/{dataset_id}", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
async def create_export(
    dataset_id: uuid.UUID,
    body: ExportRequest,
    user: CurrentUser,
    db: DBSession,
) -> JobResponse:
    """Start an export job for a dataset."""
    # Fetch dataset and verify ownership
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if dataset.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset is not ready for export (status: {dataset.status})",
        )

    # Create job
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        user_id=user.id,
        type="export",
        status="pending",
        progress=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    try:
        from app.tasks.export_task import export_dataset

        columns_json = json.dumps(body.columns) if body.columns is not None else None
        task = export_dataset.delay(
            str(dataset_id),
            str(job.id),
            body.format.value,
            columns_json,
        )

        # Store celery task id
        job.celery_task_id = task.id
        await db.commit()
        await db.refresh(job)
    except Exception as exc:
        logger.warning("Could not dispatch export task (Celery may be down): %s", exc)

    logger.info(
        "Export job %s created for dataset %s (format=%s)", job.id, dataset_id, body.format.value
    )
    return JobResponse.model_validate(job)


@router.get("/{job_id}/download", status_code=status.HTTP_200_OK)
async def download_export(
    job_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> dict[str, str]:
    """Get a presigned download URL for a completed export."""
    # Fetch job and verify ownership
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export job is not completed (status: {job.status})",
        )

    if not job.result_json or "r2_key" not in job.result_json:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export result is missing storage key",
        )

    r2_key = job.result_json["r2_key"]
    download_url = create_presigned_download_url(r2_key)

    return {"download_url": download_url}
