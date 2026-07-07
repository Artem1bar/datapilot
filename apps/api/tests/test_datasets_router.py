"""Unit tests for dataset download/delete endpoints and JSON-safe previews."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from app.routers.datasets import _json_safe_records, delete_dataset, download_dataset

USER_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = USER_ID
    return user


def _make_dataset() -> MagicMock:
    dataset = MagicMock()
    dataset.id = DATASET_ID
    dataset.user_id = USER_ID
    dataset.filename = "data.csv"
    dataset.r2_key = "uploads/u/data.csv"
    return dataset


def _db_returning(*results: object) -> AsyncMock:
    """AsyncMock db whose execute() returns the given results in order.

    A list result is exposed via .scalars().all(); anything else via
    .scalar_one_or_none().
    """
    db = AsyncMock()
    mocks = []
    for result in results:
        m = MagicMock()
        if isinstance(result, list):
            m.scalars.return_value.all.return_value = result
        else:
            m.scalar_one_or_none.return_value = result
        mocks.append(m)
    db.execute.side_effect = mocks
    return db


# ---------------------------------------------------------------------------
# _json_safe_records
# ---------------------------------------------------------------------------


class TestJsonSafeRecords:
    def test_nan_and_none_become_null(self):
        df = pd.DataFrame({"a": [1.0, np.nan], "b": ["x", None]})
        records = _json_safe_records(df)
        assert records[0]["a"] == 1.0
        assert records[1]["a"] is None
        assert records[1]["b"] is None

    def test_nat_becomes_null(self):
        df = pd.DataFrame({"d": pd.to_datetime(["2026-01-01", None])})
        records = _json_safe_records(df)
        assert records[1]["d"] is None


# ---------------------------------------------------------------------------
# DELETE /datasets/{id}
# ---------------------------------------------------------------------------


class TestDeleteDataset:
    @pytest.mark.asyncio
    async def test_404_when_missing(self):
        db = _db_returning(None)
        with pytest.raises(HTTPException) as exc_info:
            await delete_dataset(dataset_id=DATASET_ID, user=_make_user(), db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deletes_rows_and_storage_objects(self):
        dataset = _make_dataset()
        job = MagicMock()
        job.result_json = {"cleaned_r2_key": "uploads/u/data_cleaned.csv"}
        # execute order: select dataset, select jobs, delete sessions/jobs/dataset
        db = _db_returning(dataset, [job], MagicMock(), MagicMock(), MagicMock())

        with patch("app.routers.datasets.delete_object") as mock_delete:
            await delete_dataset(dataset_id=DATASET_ID, user=_make_user(), db=db)

        deleted_keys = {call.args[0] for call in mock_delete.call_args_list}
        assert deleted_keys == {"uploads/u/data.csv", "uploads/u/data_cleaned.csv"}
        assert db.execute.await_count == 5
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_storage_failure_does_not_block_delete(self):
        dataset = _make_dataset()
        db = _db_returning(dataset, [], MagicMock(), MagicMock(), MagicMock())

        with patch("app.routers.datasets.delete_object", side_effect=RuntimeError("boom")):
            await delete_dataset(dataset_id=DATASET_ID, user=_make_user(), db=db)

        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /datasets/{id}/download
# ---------------------------------------------------------------------------


class TestDownloadDataset:
    @pytest.mark.asyncio
    async def test_404_when_missing(self):
        db = _db_returning(None)
        with pytest.raises(HTTPException) as exc_info:
            await download_dataset(dataset_id=DATASET_ID, user=_make_user(), db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_prefers_latest_cleaned_file(self):
        dataset = _make_dataset()
        clean_job = MagicMock()
        clean_job.result_json = {"cleaned_r2_key": "uploads/u/data_cleaned.csv"}
        db = _db_returning(dataset, clean_job)

        with patch(
            "app.routers.datasets.download_file_bytes", return_value=b"csvbytes"
        ) as mock_download:
            response = await download_dataset(dataset_id=DATASET_ID, user=_make_user(), db=db)

        mock_download.assert_called_once_with("uploads/u/data_cleaned.csv")
        assert 'filename="data_cleaned.csv"' in response.headers["content-disposition"]
        assert response.media_type == "text/csv"

    @pytest.mark.asyncio
    async def test_falls_back_to_original_file(self):
        dataset = _make_dataset()
        db = _db_returning(dataset, None)

        with patch("app.routers.datasets.download_file_bytes", return_value=b"x") as mock_download:
            response = await download_dataset(dataset_id=DATASET_ID, user=_make_user(), db=db)

        mock_download.assert_called_once_with("uploads/u/data.csv")
        assert 'filename="data.csv"' in response.headers["content-disposition"]
