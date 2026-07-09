"""Tests for cleaning revert + before/after comparison endpoints.

Trust-UX work (2B#5/#6): cleaning never creates a new dataset row — the
cleaned file lives in storage under the clean job's ``cleaned_r2_key`` and
``GET /datasets/{id}/download`` substitutes the latest completed clean job's
file. Revert marks that job so substitution skips it; comparison diffs the
original file against the job's cleaned file.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.cleaning import get_cleaning_comparison, revert_cleaning
from app.routers.datasets import download_dataset, get_history

USER_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = USER_ID
    return user


def _make_dataset() -> MagicMock:
    dataset = MagicMock()
    dataset.id = DATASET_ID
    dataset.user_id = USER_ID
    dataset.filename = "orders.csv"
    dataset.r2_key = "uploads/u/orders.csv"
    return dataset


def _make_clean_job(
    status: str = "completed",
    result_json: dict | None = ...,
) -> MagicMock:
    job = MagicMock()
    job.id = JOB_ID
    job.dataset_id = DATASET_ID
    job.user_id = USER_ID
    job.type = "clean"
    job.status = status
    if result_json is ...:
        result_json = {
            "cleaned_r2_key": "uploads/u/orders_cleaned.csv",
            "original_rows": 15,
            "cleaned_rows": 13,
            "cells_modified": 25,
        }
    job.result_json = result_json
    return job


def _db_returning(*results: object) -> AsyncMock:
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
# POST /cleaning/{job_id}/revert
# ---------------------------------------------------------------------------


class TestRevertCleaning:
    @pytest.mark.anyio
    async def test_marks_job_reverted_and_commits(self):
        job = _make_clean_job()
        db = _db_returning(job)

        resp = await revert_cleaning(JOB_ID, _make_user(), db)

        assert job.result_json["reverted"] is True
        db.commit.assert_awaited()
        assert resp["reverted"] is True
        assert resp["job_id"] == str(JOB_ID)

    @pytest.mark.anyio
    async def test_404_when_job_missing(self):
        db = _db_returning(None)
        with pytest.raises(HTTPException) as exc:
            await revert_cleaning(JOB_ID, _make_user(), db)
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_400_when_job_not_completed(self):
        db = _db_returning(_make_clean_job(status="running"))
        with pytest.raises(HTTPException) as exc:
            await revert_cleaning(JOB_ID, _make_user(), db)
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_idempotent_when_already_reverted(self):
        job = _make_clean_job()
        job.result_json = {**job.result_json, "reverted": True}
        db = _db_returning(job)

        resp = await revert_cleaning(JOB_ID, _make_user(), db)

        assert resp["reverted"] is True


# ---------------------------------------------------------------------------
# Download substitution skips reverted clean jobs
# ---------------------------------------------------------------------------


class TestDownloadSkipsReverted:
    @pytest.mark.anyio
    async def test_reverted_latest_job_falls_back_to_original(self):
        dataset = _make_dataset()
        reverted = _make_clean_job()
        reverted.result_json = {**reverted.result_json, "reverted": True}
        db = _db_returning(dataset, [reverted])

        with patch("app.routers.datasets.download_file_bytes", return_value=b"original") as dl:
            await download_dataset(DATASET_ID, _make_user(), db)

        dl.assert_called_once_with(dataset.r2_key)

    @pytest.mark.anyio
    async def test_reverted_latest_falls_back_to_earlier_clean(self):
        dataset = _make_dataset()
        reverted = _make_clean_job()
        reverted.result_json = {**reverted.result_json, "reverted": True}
        older = _make_clean_job()
        older.result_json = {
            **older.result_json,
            "cleaned_r2_key": "uploads/u/orders_cleaned_v1.csv",
        }
        db = _db_returning(dataset, [reverted, older])

        with patch("app.routers.datasets.download_file_bytes", return_value=b"v1") as dl:
            await download_dataset(DATASET_ID, _make_user(), db)

        dl.assert_called_once_with("uploads/u/orders_cleaned_v1.csv")

    @pytest.mark.anyio
    async def test_non_reverted_latest_still_wins(self):
        dataset = _make_dataset()
        job = _make_clean_job()
        db = _db_returning(dataset, [job])

        with patch("app.routers.datasets.download_file_bytes", return_value=b"clean") as dl:
            await download_dataset(DATASET_ID, _make_user(), db)

        dl.assert_called_once_with("uploads/u/orders_cleaned.csv")


# ---------------------------------------------------------------------------
# GET /cleaning/{job_id}/comparison
# ---------------------------------------------------------------------------

_BEFORE_CSV = b"name,score\n  alice ,80\nbob,90\n"
_AFTER_CSV = b"name,score\nalice,80\nbob,90\n"


class TestCleaningComparison:
    @pytest.mark.anyio
    async def test_diffs_original_against_cleaned_file(self):
        job = _make_clean_job()
        dataset = _make_dataset()
        db = _db_returning(job, dataset)

        def fake_download(key: str) -> bytes:
            return _BEFORE_CSV if key == dataset.r2_key else _AFTER_CSV

        with patch("app.routers.cleaning.download_file_bytes", side_effect=fake_download):
            resp = await get_cleaning_comparison(JOB_ID, _make_user(), db)

        assert resp["summary"]["rows_before"] == 2
        assert resp["summary"]["rows_after"] == 2
        assert resp["datasets"]["before"]["id"] == str(DATASET_ID)
        assert resp["datasets"]["before"]["filename"] == "orders.csv"
        assert resp["datasets"]["after"]["id"] == str(JOB_ID)
        # The whitespace fix on row 0 shows up as a sample change
        changed_cols = {c["column"] for c in resp["sample_changes"]}
        assert "name" in changed_cols

    @pytest.mark.anyio
    async def test_404_when_job_missing(self):
        db = _db_returning(None)
        with pytest.raises(HTTPException) as exc:
            await get_cleaning_comparison(JOB_ID, _make_user(), db)
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_400_when_job_not_completed(self):
        db = _db_returning(_make_clean_job(status="running"))
        with pytest.raises(HTTPException) as exc:
            await get_cleaning_comparison(JOB_ID, _make_user(), db)
        assert exc.value.status_code == 400

    @pytest.mark.anyio
    async def test_500_when_cleaned_key_missing(self):
        db = _db_returning(_make_clean_job(result_json={"cleaned_rows": 1}))
        with pytest.raises(HTTPException) as exc:
            await get_cleaning_comparison(JOB_ID, _make_user(), db)
        assert exc.value.status_code == 500


# ---------------------------------------------------------------------------
# History summary reads original_rows (task writes that key, not rows_before)
# ---------------------------------------------------------------------------


class TestHistoryRowsBefore:
    @pytest.mark.anyio
    async def test_summary_rows_before_from_original_rows(self):
        dataset = _make_dataset()
        job = _make_clean_job()
        db = _db_returning(dataset, [job])

        resp = await get_history(DATASET_ID, _make_user(), db)

        assert resp["entries"][0]["summary"]["rows_before"] == 15
