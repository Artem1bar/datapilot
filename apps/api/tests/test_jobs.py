"""Unit tests for the /jobs/{job_id} router endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.routers.jobs import get_job

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()


def _make_user(user_id: uuid.UUID = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _make_job(user_id: uuid.UUID = USER_ID) -> MagicMock:
    j = MagicMock()
    j.id = JOB_ID
    j.dataset_id = DATASET_ID
    j.user_id = user_id
    j.type = "clean"
    j.status = "completed"
    j.progress = 100
    j.result_json = None
    j.error_text = None
    j.created_at = datetime(2026, 1, 1, 12, 0, 0)
    j.completed_at = None
    return j


def _make_db(query_result: object = None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = query_result
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------


class TestGetJob:
    @pytest.mark.asyncio
    async def test_returns_job_for_owner(self) -> None:
        job = _make_job()
        response = await get_job(job_id=JOB_ID, user=_make_user(), db=_make_db(job))

        assert response.id == JOB_ID
        assert response.status == "completed"
        assert response.progress == 100
        assert response.type == "clean"

    @pytest.mark.asyncio
    async def test_returns_dataset_id(self) -> None:
        job = _make_job()
        response = await get_job(job_id=JOB_ID, user=_make_user(), db=_make_db(job))

        assert response.dataset_id == DATASET_ID

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_job(job_id=JOB_ID, user=_make_user(), db=_make_db(None))

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Job not found"

    @pytest.mark.asyncio
    async def test_raises_404_for_wrong_user(self) -> None:
        # DB query filters by user_id — wrong user gets None back
        other_user = _make_user(user_id=OTHER_USER_ID)
        with pytest.raises(HTTPException) as exc_info:
            await get_job(job_id=JOB_ID, user=other_user, db=_make_db(None))

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_db_queried_once(self) -> None:
        db = _make_db(_make_job())
        await get_job(job_id=JOB_ID, user=_make_user(), db=db)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_propagates_error_text(self) -> None:
        job = _make_job()
        job.status = "failed"
        job.error_text = "Something went wrong"
        response = await get_job(job_id=JOB_ID, user=_make_user(), db=_make_db(job))

        assert response.status == "failed"
        assert response.error_text == "Something went wrong"

    @pytest.mark.asyncio
    async def test_pending_job_progress_zero(self) -> None:
        job = _make_job()
        job.status = "pending"
        job.progress = 0
        response = await get_job(job_id=JOB_ID, user=_make_user(), db=_make_db(job))

        assert response.status == "pending"
        assert response.progress == 0
