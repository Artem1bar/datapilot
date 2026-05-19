"""Cleaning plan and recipe endpoints."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.dataset import Dataset
from app.models.job import Job
from app.schemas import CleaningStep, JobResponse, VerificationResult
from app.services.storage import download_file_bytes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cleaning"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class GeneratePlanRequest(BaseModel):
    """Optional request body for generating a cleaning plan with custom instructions."""
    user_instructions: str | None = Field(
        None,
        max_length=2000,
        description="Additional cleaning instructions from the user",
    )


class ApplyCleaningRequest(BaseModel):
    """Request body for applying a (possibly modified) cleaning plan."""
    steps: list[CleaningStep] = Field(..., min_length=1, description="Cleaning steps to apply")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:  # noqa: F821
    """Read the full file into a DataFrame."""
    import pandas as pd

    lower = filename.lower()
    buf = io.BytesIO(file_bytes)
    if lower.endswith(".csv"):
        return pd.read_csv(buf)
    elif lower.endswith((".xls", ".xlsx")):
        return pd.read_excel(buf)
    elif lower.endswith(".parquet"):
        return pd.read_parquet(buf)
    elif lower.endswith(".json"):
        return pd.read_json(buf)
    elif lower.endswith((".tsv", ".tab")):
        return pd.read_csv(buf, sep="\t")
    else:
        return pd.read_csv(buf)


def _read_all_rows(file_bytes: bytes, filename: str, max_rows: int = 500) -> list[dict[str, Any]]:
    """Read up to max_rows rows from a file as a list of dicts.

    Sends ALL rows for small datasets so the AI sees every value.
    Caps at max_rows for large datasets to stay within token limits.
    """
    df = _read_dataframe(file_bytes, filename)
    if len(df) > max_rows:
        # For large datasets, take first 250 + 250 random interior rows
        import pandas as pd
        head = df.head(250)
        rest = df.iloc[250:].sample(min(250, len(df) - 250), random_state=42)
        df = pd.concat([head, rest]).reset_index(drop=True)
    return df.fillna("").to_dict(orient="records")


async def _get_dataset_or_404(
    dataset_id: uuid.UUID, user_id: uuid.UUID, db,
) -> Dataset:
    """Fetch a dataset owned by the user or raise 404."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{dataset_id}/plan", status_code=status.HTTP_200_OK)
async def create_cleaning_plan(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    body: GeneratePlanRequest | None = None,
) -> JobResponse:
    """Generate a cleaning plan for a dataset using AI."""
    from app.services.rate_limit import check_rate_limit

    await check_rate_limit(str(user.id), action="cleaning_plan", max_calls=20, window_seconds=3600)

    dataset = await _get_dataset_or_404(dataset_id, user.id, db)

    if dataset.status != "ready" or dataset.profile_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset must be profiled before generating a cleaning plan. "
                   f"Current status: '{dataset.status}'",
        )

    # Download file — run sync IO in thread
    try:
        file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    except Exception as exc:
        logger.error("Failed to download dataset %s: %s", dataset_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to download dataset file from storage",
        )

    # Read ALL rows (capped at 500 for very large files) so Claude sees every value
    sample_rows = await asyncio.to_thread(_read_all_rows, file_bytes, dataset.filename)

    # Always compute fresh data-quality flags from the actual file — don't rely on
    # whatever the profiler stored (it may have run before this detection code existed)
    def _compute_fresh_quality_flags(fb: bytes, fname: str) -> dict:
        from app.tasks.profile_task import detect_quality_issues
        df = _read_dataframe(fb, fname)
        return detect_quality_issues(df)

    fresh_quality = await asyncio.to_thread(_compute_fresh_quality_flags, file_bytes, dataset.filename)

    # Merge fresh flags into the profile (always override stale stored flags)
    profile_with_flags = dict(dataset.profile_json or {})
    if fresh_quality:
        profile_with_flags["data_quality"] = fresh_quality
    elif "data_quality" in profile_with_flags:
        del profile_with_flags["data_quality"]  # Remove stale flags if file is now clean

    logger.info(
        "Dataset %s: %d rows sent to Claude, %d quality flags detected",
        dataset_id, len(sample_rows), len(fresh_quality)
    )

    # Generate cleaning plan via Claude
    from app.services.cleaning import generate_cleaning_plan

    user_instructions = body.user_instructions if body else None

    try:
        steps = await asyncio.to_thread(
            generate_cleaning_plan,
            profile_json=profile_with_flags,
            sample_rows=sample_rows,
            dataset_id=str(dataset_id),
            user_instructions=user_instructions,
        )
    except Exception as exc:
        logger.exception("Failed to generate cleaning plan for dataset %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to generate cleaning plan: {exc}",
        )

    # Create a job to store the plan
    plan_data = {
        "steps": steps,
        "summary": f"AI-generated cleaning plan with {len(steps)} steps",
        "dataset_id": str(dataset_id),
    }

    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=user.id,
        type="cleaning_plan",
        status="completed",
        progress=100,
        result_json=plan_data,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info("Generated cleaning plan for dataset %s with %d steps", dataset_id, len(steps))
    return JobResponse.model_validate(job)


@router.get("/{dataset_id}/plan", status_code=status.HTTP_200_OK)
async def get_cleaning_plan(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> JobResponse:
    """Retrieve the most recent cleaning plan for a dataset."""
    dataset = await _get_dataset_or_404(dataset_id, user.id, db)

    result = await db.execute(
        select(Job)
        .where(
            Job.dataset_id == dataset.id,
            Job.user_id == user.id,
            Job.type == "cleaning_plan",
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cleaning plan found for this dataset. Generate one first.",
        )

    return JobResponse.model_validate(job)


@router.post("/{dataset_id}/apply", status_code=status.HTTP_202_ACCEPTED)
async def apply_cleaning_plan(
    dataset_id: uuid.UUID,
    body: ApplyCleaningRequest,
    user: CurrentUser,
    db: DBSession,
) -> JobResponse:
    """Apply cleaning steps to a dataset (dispatches a background task)."""
    from app.services.rate_limit import check_rate_limit

    await check_rate_limit(str(user.id), action="cleaning_apply", max_calls=30, window_seconds=3600)

    dataset = await _get_dataset_or_404(dataset_id, user.id, db)

    if dataset.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dataset must be in 'ready' state to apply cleaning. "
                   f"Current status: '{dataset.status}'",
        )

    # Serialize steps for the Celery task
    steps_dicts = [step.model_dump() for step in body.steps]

    # Create a job record
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=user.id,
        type="clean",
        status="pending",
        progress=0,
        input_json={"steps": steps_dicts},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    try:
        from app.tasks.cleaning_task import clean_dataset

        task = clean_dataset.delay(str(dataset.id), str(job.id), json.dumps(steps_dicts))
        job.celery_task_id = task.id
        await db.commit()
        await db.refresh(job)
    except Exception as exc:
        logger.warning("Could not dispatch cleaning task (Celery may be down): %s", exc)
        job.status = "failed"
        job.error_text = f"Failed to dispatch cleaning task: {exc}"
        await db.commit()
        await db.refresh(job)

    logger.info("Dispatched cleaning task for dataset %s, job %s", dataset_id, job.id)
    return JobResponse.model_validate(job)


@router.get("/{job_id}/download")
async def download_cleaned_file(
    job_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> StreamingResponse:
    """Stream the cleaned file directly to the browser.

    Downloads the file from storage server-side and streams it to the client,
    so it works regardless of whether MinIO/R2 is publicly accessible.
    """
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id, Job.type == "clean")
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cleaning job not found")

    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cleaning job is not completed (status: {job.status})",
        )

    if not job.result_json or "cleaned_r2_key" not in job.result_json:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cleaned file key not found in job result",
        )

    r2_key: str = job.result_json["cleaned_r2_key"]
    # Derive original filename from the key, e.g. "uploads/.../foo_cleaned.xlsx"
    filename = r2_key.split("/")[-1]

    # Detect content-type from extension
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif lower.endswith(".xls"):
        content_type = "application/vnd.ms-excel"
    elif lower.endswith(".csv"):
        content_type = "text/csv"
    elif lower.endswith(".parquet"):
        content_type = "application/octet-stream"
    elif lower.endswith(".json"):
        content_type = "application/json"
    else:
        content_type = "application/octet-stream"

    # Download from storage server-side and stream to browser
    try:
        file_bytes = await asyncio.to_thread(download_file_bytes, r2_key)
    except Exception as exc:
        logger.exception("Failed to download cleaned file from storage: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cleaned file from storage.",
        )

    import io as _io

    return StreamingResponse(
        content=_io.BytesIO(file_bytes),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(file_bytes)),
        },
    )


@router.get("/{job_id}/verification", status_code=status.HTTP_200_OK)
async def get_verification_report(
    job_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> VerificationResult:
    """Retrieve the verification report for a completed cleaning job."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id, Job.type == "clean")
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cleaning job not found")

    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cleaning job is not completed (status: {job.status})",
        )

    verification = (job.result_json or {}).get("verification")
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No verification report available for this job",
        )

    return VerificationResult(**verification)


# Note: Recipe CRUD endpoints are mounted at /api/v1/recipes via the recipes router.
