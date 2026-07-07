"""Spreadsheet manipulation endpoints — parse, preview, apply, undo."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.dataset import Dataset
from app.schemas.manipulation import (
    ManipulationApplyRequest,
    ManipulationParseRequest,
    ManipulationPreview,
    ManipulationResult,
    ManipulationUndoRequest,
)
from app.services.manipulation import (
    ManipulationError,
    apply_manipulation,
    create_snapshot,
    generate_preview,
    parse_manipulation_intent,
)
from app.services.manipulation_executor import ManipulationError as ExecError
from app.services.storage import download_file_bytes, upload_file_bytes
from app.utils.dataframe import read_dataframe, to_sample_records

logger = logging.getLogger(__name__)

router = APIRouter(tags=["manipulation"])


async def _get_dataset_or_404(dataset_id: uuid.UUID, user_id: uuid.UUID, db) -> Dataset:
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


@router.post("/{dataset_id}/parse", response_model=ManipulationPreview)
async def parse_command(
    dataset_id: uuid.UUID,
    body: ManipulationParseRequest,
    user: CurrentUser,
    db: DBSession,
) -> ManipulationPreview:
    """Parse a natural language command into structured operations and return a preview."""
    from app.services.rate_limit import check_rate_limit

    await check_rate_limit(
        str(user.id), action="manipulation_parse", max_calls=30, window_seconds=3600
    )

    dataset = await _get_dataset_or_404(dataset_id, user.id, db)

    if not dataset.profile_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset has not been profiled yet.",
        )

    # Download and read the dataset
    file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    df = await asyncio.to_thread(read_dataframe, file_bytes, dataset.filename)

    column_names = list(df.columns)
    dtypes = {col: str(df[col].dtype) for col in df.columns}
    sample_rows = to_sample_records(df.head(5))

    # Parse the command using AI
    try:
        operations = await asyncio.to_thread(
            parse_manipulation_intent,
            body.command,
            column_names,
            dtypes,
            sample_rows,
        )
    except (ManipulationError, ExecError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    # Generate a preview
    try:
        preview = await asyncio.to_thread(generate_preview, df, operations)
    except (ManipulationError, ExecError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return ManipulationPreview(**preview)


@router.post("/{dataset_id}/apply", response_model=ManipulationResult)
async def apply_operations(
    dataset_id: uuid.UUID,
    body: ManipulationApplyRequest,
    user: CurrentUser,
    db: DBSession,
) -> ManipulationResult:
    """Apply manipulation operations to the dataset. Creates a snapshot for undo."""
    dataset = await _get_dataset_or_404(dataset_id, user.id, db)

    # Create snapshot before applying
    try:
        snapshot_id, _snapshot_key = await asyncio.to_thread(create_snapshot, dataset.r2_key)
    except Exception as e:
        logger.warning("Failed to create snapshot: %s", e)
        snapshot_id = ""

    # Download, apply, upload
    file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    operations = [op.model_dump() for op in body.operations]

    try:
        result_df, metadata = await asyncio.to_thread(
            apply_manipulation,
            file_bytes,
            dataset.filename,
            operations,
            dataset.r2_key,
        )
    except (ManipulationError, ExecError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    # Update dataset metadata
    dataset.row_count = metadata["new_row_count"]
    dataset.col_count = metadata["new_col_count"]
    await db.commit()

    return ManipulationResult(
        success=True,
        snapshot_id=snapshot_id,
        sample_rows=result_df.head(5).fillna("").to_dict(orient="records"),
        **metadata,
    )


@router.post("/{dataset_id}/undo", response_model=ManipulationResult)
async def undo_manipulation(
    dataset_id: uuid.UUID,
    body: ManipulationUndoRequest,
    user: CurrentUser,
    db: DBSession,
) -> ManipulationResult:
    """Restore dataset from a snapshot."""
    dataset = await _get_dataset_or_404(dataset_id, user.id, db)

    # Find and restore snapshot
    snapshot_key = f"snapshots/{body.snapshot_id}/{dataset.r2_key.split('/')[-1]}"
    try:
        snapshot_bytes = await asyncio.to_thread(download_file_bytes, snapshot_key)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    # Upload snapshot back to original key
    await asyncio.to_thread(upload_file_bytes, dataset.r2_key, snapshot_bytes)

    # Read the restored file to get updated metadata
    df = await asyncio.to_thread(read_dataframe, snapshot_bytes, dataset.filename)
    dataset.row_count = len(df)
    dataset.col_count = len(df.columns)
    await db.commit()

    return ManipulationResult(
        success=True,
        snapshot_id=body.snapshot_id,
        new_row_count=len(df),
        new_col_count=len(df.columns),
        sample_rows=df.head(5).fillna("").to_dict(orient="records"),
    )
