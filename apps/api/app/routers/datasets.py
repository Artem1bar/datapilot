"""Dataset CRUD and upload flow."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sqla_delete
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DBSession
from app.models.chat_session import ChatSession
from app.models.dataset import Dataset
from app.models.job import Job
from app.schemas import (
    ConfirmUploadRequest,
    DatasetResponse,
    JobResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.dataset_versions import pick_effective_r2_key
from app.services.storage import (
    create_presigned_upload_url,
    delete_object,
    download_file_bytes,
    generate_upload_key,
    upload_file_bytes,
)
from app.utils.dataframe import read_dataframe
from app.utils.file_validation import validate_file_content

logger = logging.getLogger(__name__)

router = APIRouter(tags=["datasets"])


def _validate_upload(data: bytes, filename: str) -> None:
    """Reject oversize or content-mismatched uploads. Raises HTTPException."""
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "File exceeds the maximum upload size of "
                f"{settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            ),
        )
    if not validate_file_content(data, filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match its extension or is empty/corrupt",
        )


_CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".parquet": "application/octet-stream",
    ".json": "application/json",
}


def _content_type_for(filename: str) -> str:
    lower = filename.lower()
    for ext, content_type in _CONTENT_TYPES.items():
        if lower.endswith(ext):
            return content_type
    return "application/octet-stream"


def _json_safe_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → records with real None for missing values (JSON null)."""
    safe = df.astype(object).where(df.notna(), None)
    return safe.to_dict(orient="records")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    user: CurrentUser,
    db: DBSession,
    file: UploadFile = File(...),
) -> dict:
    """Accept a file upload directly (no presigned URL needed — avoids CORS)."""
    data = await file.read()
    filename = file.filename or "upload.csv"
    content_type = file.content_type or "application/octet-stream"

    # Reject oversize / content-mismatched files before touching storage.
    _validate_upload(data, filename)

    r2_key = generate_upload_key(user.id, filename)
    upload_file_bytes(r2_key, data, content_type)

    dataset = Dataset(
        id=uuid.uuid4(),
        user_id=user.id,
        filename=filename,
        r2_key=r2_key,
        file_size_bytes=len(data),
        status="profiling",
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=user.id,
        type="profile",
        status="pending",
        progress=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    try:
        from app.tasks.profile_task import profile_dataset

        task = profile_dataset.delay(str(dataset.id), str(job.id))
        job.celery_task_id = task.id
        await db.commit()
    except Exception as exc:
        logger.warning("Could not dispatch profile task: %s", exc, exc_info=True)

    return {"dataset_id": str(dataset.id)}


@router.post("/upload-url", response_model=UploadUrlResponse, status_code=status.HTTP_201_CREATED)
async def create_upload_url(
    body: UploadUrlRequest,
    user: CurrentUser,
    db: DBSession,
) -> UploadUrlResponse:
    """Generate a presigned upload URL and create a pending dataset record."""
    r2_key = generate_upload_key(user.id, body.filename)
    upload_url = create_presigned_upload_url(r2_key, content_type=body.content_type)

    dataset = Dataset(
        id=uuid.uuid4(),
        user_id=user.id,
        filename=body.filename,
        r2_key=r2_key,
        file_size_bytes=body.file_size_bytes,
        status="uploaded",
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    return UploadUrlResponse(
        upload_url=upload_url,
        r2_key=r2_key,
        dataset_id=dataset.id,
    )


@router.post(
    "/{dataset_id}/confirm", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
async def confirm_upload(
    dataset_id: uuid.UUID,
    body: ConfirmUploadRequest,
    user: CurrentUser,
    db: DBSession,
) -> JobResponse:
    """Confirm that the file has been uploaded to S3 and dispatch profiling."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if dataset.status != "uploaded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dataset is already in '{dataset.status}' state",
        )

    # Update metadata if provided
    if body.file_size_bytes is not None:
        dataset.file_size_bytes = body.file_size_bytes
    if body.filename:
        dataset.filename = body.filename

    # Validate the object now that it has landed in storage (magic bytes + real
    # size, not the client-reported size). Reject and clean up bad content.
    try:
        landed = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    except Exception as exc:
        logger.error("Failed to read uploaded object %s for validation: %s", dataset.r2_key, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to read the uploaded file for validation",
        )
    try:
        _validate_upload(landed, dataset.filename)
    except HTTPException:
        # Remove the bad object and mark the dataset errored so it isn't retried blindly.
        try:
            await asyncio.to_thread(delete_object, dataset.r2_key)
        except Exception:
            logger.warning("Failed to delete invalid upload %s", dataset.r2_key)
        dataset.status = "error"
        await db.commit()
        raise

    dataset.status = "profiling"

    # Create a profiling job
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=user.id,
        type="profile",
        status="pending",
        progress=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch the Celery profiling task
    try:
        from app.tasks.profile_task import profile_dataset

        task = profile_dataset.delay(str(dataset.id), str(job.id))
        job.celery_task_id = task.id
        await db.commit()
        await db.refresh(job)
    except Exception as exc:
        logger.warning("Could not dispatch profile task: %s", exc, exc_info=True)

    return JobResponse.model_validate(job)


@router.get("/", response_model=list[DatasetResponse])
async def list_datasets(
    user: CurrentUser,
    db: DBSession,
) -> list[DatasetResponse]:
    """List all datasets belonging to the authenticated user."""
    result = await db.execute(
        select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc())
    )
    datasets = result.scalars().all()
    return [DatasetResponse.model_validate(d) for d in datasets]


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> DatasetResponse:
    """Get a single dataset by ID."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return DatasetResponse.model_validate(dataset)


@router.get("/{dataset_id}/schema")
async def get_schema(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    """Infer and return the dataset schema."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    df = await asyncio.to_thread(read_dataframe, file_bytes, dataset.filename)

    from app.services.schema_inference import infer_schema

    return await asyncio.to_thread(infer_schema, df)


@router.post("/{dataset_id}/validate-schema")
async def validate_schema(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    schema: dict | None = None,
) -> dict:
    """Validate dataset against a schema (inferred or provided)."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    df = await asyncio.to_thread(read_dataframe, file_bytes, dataset.filename)

    from app.services.schema_inference import infer_schema, validate_against_schema

    if schema is None:
        schema = infer_schema(df)

    violations = await asyncio.to_thread(validate_against_schema, df, schema)
    return {
        "schema": schema,
        "violations": violations,
        "is_valid": len([v for v in violations if v["severity"] == "error"]) == 0,
    }


@router.get("/{dataset_id}/preview")
async def preview_data(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    page: int = 1,
    page_size: int = 50,
    sort_by: str | None = None,
    sort_desc: bool = False,
    filter_column: str | None = None,
    filter_value: str | None = None,
) -> dict:
    """Return paginated dataset rows with quality annotations."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    df = await asyncio.to_thread(read_dataframe, file_bytes, dataset.filename)

    # Apply filter
    if filter_column and filter_value and filter_column in df.columns:
        mask = df[filter_column].astype(str).str.contains(filter_value, case=False, na=False)
        df = df[mask]

    # Apply sort
    if sort_by and sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=not sort_desc, na_position="last")

    total_rows = len(df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size

    page_df = df.iloc[start:end]

    # Build quality annotations
    quality_flags = dataset.profile_json.get("data_quality", {}) if dataset.profile_json else {}
    cell_annotations: dict[str, list[dict]] = {}
    for col in page_df.columns:
        col_flags = quality_flags.get(col, {})
        for row_idx, (_df_idx, val) in enumerate(page_df[col].items()):
            annotations: list[dict] = []
            if pd.isna(val):
                annotations.append({"type": "null", "severity": "warning"})
            elif col_flags.get("has_extreme_outliers") and pd.api.types.is_numeric_dtype(
                page_df[col]
            ):
                numeric_val = pd.to_numeric(val, errors="coerce")
                if numeric_val is not None and not pd.isna(numeric_val):
                    q75 = (
                        (dataset.profile_json or {})
                        .get("columns", {})
                        .get(col, {})
                        .get("q75", float("inf"))
                    )
                    if numeric_val > q75 * 3:
                        annotations.append({"type": "outlier", "severity": "error"})
            if annotations:
                cell_annotations[f"{row_idx}:{col}"] = annotations

    # Column metadata
    columns = []
    for col in page_df.columns:
        col_info = (
            dataset.profile_json.get("columns", {}).get(col, {}) if dataset.profile_json else {}
        )
        columns.append(
            {
                "name": col,
                "dtype": col_info.get("dtype", str(page_df[col].dtype)),
                "null_pct": col_info.get("null_pct", 0),
                "has_issues": col in quality_flags,
            }
        )

    return {
        "columns": columns,
        "rows": _json_safe_records(page_df),
        "row_indices": page_df.index.tolist(),
        "total_rows": total_rows,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "cell_annotations": cell_annotations,
    }


@router.post("/{dataset_id}/compare/{other_dataset_id}")
async def compare_datasets_endpoint(
    dataset_id: uuid.UUID,
    other_dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    """Compare two datasets and return a diff report."""
    from app.services.comparison import compare_datasets as compare_fn

    # Fetch both datasets
    result1 = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset1 = result1.scalar_one_or_none()
    if dataset1 is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    result2 = await db.execute(
        select(Dataset).where(Dataset.id == other_dataset_id, Dataset.user_id == user.id)
    )
    dataset2 = result2.scalar_one_or_none()
    if dataset2 is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comparison dataset not found"
        )

    bytes1 = await asyncio.to_thread(download_file_bytes, dataset1.r2_key)
    bytes2 = await asyncio.to_thread(download_file_bytes, dataset2.r2_key)

    df1 = await asyncio.to_thread(read_dataframe, bytes1, dataset1.filename)
    df2 = await asyncio.to_thread(read_dataframe, bytes2, dataset2.filename)

    report = await asyncio.to_thread(compare_fn, df1, df2)
    report["datasets"] = {
        "before": {"id": str(dataset_id), "filename": dataset1.filename},
        "after": {"id": str(other_dataset_id), "filename": dataset2.filename},
    }
    return report


@router.get("/{dataset_id}/history")
async def get_history(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    """Get the operation history for a dataset."""
    from sqlalchemy import desc

    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    # Get history from jobs
    jobs_result = await db.execute(
        select(Job)
        .where(Job.dataset_id == dataset_id, Job.user_id == user.id)
        .order_by(desc(Job.created_at))
    )
    jobs = jobs_result.scalars().all()

    history = []
    for job in jobs:
        entry: dict = {
            "id": str(job.id),
            "type": job.type,
            "status": job.status,
            "progress": job.progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        if job.result_json:
            entry["summary"] = {
                # The clean task stores the pre-clean count as "original_rows".
                "rows_before": job.result_json.get(
                    "original_rows", job.result_json.get("rows_before")
                ),
                "rows_after": job.result_json.get("cleaned_rows"),
                "cells_modified": job.result_json.get("cells_modified"),
            }
        history.append(entry)

    return {
        "dataset_id": str(dataset_id),
        "filename": dataset.filename,
        "entries": history,
    }


@router.get("/{dataset_id}/download")
async def download_dataset(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> StreamingResponse:
    """Stream the dataset file to the browser (latest cleaned version if any)."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    jobs_result = await db.execute(
        select(Job)
        .where(
            Job.dataset_id == dataset.id,
            Job.user_id == user.id,
            Job.type == "clean",
            Job.status == "completed",
        )
        .order_by(Job.created_at.desc())
    )
    r2_key = pick_effective_r2_key(dataset.r2_key, jobs_result.scalars().all())

    try:
        file_bytes = await asyncio.to_thread(download_file_bytes, r2_key)
    except Exception:
        logger.exception("Failed to download dataset file %s", r2_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve file from storage.",
        )

    filename = r2_key.split("/")[-1]
    return StreamingResponse(
        content=io.BytesIO(file_bytes),
        media_type=_content_type_for(filename),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(file_bytes)),
        },
    )


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> None:
    """Delete a dataset, its jobs and chat sessions, and its stored files."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    jobs_result = await db.execute(
        select(Job).where(Job.dataset_id == dataset.id, Job.user_id == user.id)
    )
    jobs = jobs_result.scalars().all()

    keys = {dataset.r2_key}
    for job in jobs:
        if not job.result_json:
            continue
        for key_field in ("cleaned_r2_key", "r2_key"):
            key = job.result_json.get(key_field)
            if isinstance(key, str) and key:
                keys.add(key)

    for key in keys:
        try:
            await asyncio.to_thread(delete_object, key)
        except Exception as exc:
            # Best-effort: storage cleanup must not block dataset deletion
            logger.warning("Failed to delete stored object %s: %s", key, exc)

    await db.execute(sqla_delete(ChatSession).where(ChatSession.dataset_id == dataset.id))
    await db.execute(sqla_delete(Job).where(Job.dataset_id == dataset.id))
    await db.execute(sqla_delete(Dataset).where(Dataset.id == dataset.id))
    await db.commit()
