"""Data dictionary endpoints."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.dataset import Dataset
from app.services.data_dictionary import generate_data_dictionary
from app.services.storage import download_file_bytes
from app.utils.dataframe import to_sample_records

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dictionary"])


@router.get("/{dataset_id}/dictionary")
async def get_data_dictionary(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    """Generate an AI-powered data dictionary for a dataset."""
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if not dataset.profile_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset not profiled yet"
        )

    file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
    lower = dataset.filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes), nrows=10)
    elif lower.endswith(".parquet"):
        df = pd.read_parquet(io.BytesIO(file_bytes))
        df = df.head(10)
    else:
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=10)
    sample_rows = to_sample_records(df)

    dictionary = await asyncio.to_thread(
        generate_data_dictionary,
        dataset.profile_json,
        sample_rows,
    )
    return dictionary
