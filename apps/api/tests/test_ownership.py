"""Ownership matrix: a user cannot read another user's resources.

Every user-scoped query filters by ``user_id == user.id`` (audited across all
routers), so a request for a resource the caller does not own resolves to
``None`` and the handler returns 404. These tests lock that contract for the
job/cleaning endpoints; recipe and dataset cross-user cases live in their own
router tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.routers.cleaning import get_cleaning_plan, get_verification_report
from app.routers.jobs import get_job


def _other_user() -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    return u


def _db_returns_none() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_get_job_is_not_visible_cross_user():
    with pytest.raises(HTTPException) as exc:
        await get_job(uuid.uuid4(), _other_user(), _db_returns_none())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_cleaning_plan_is_not_visible_cross_user():
    with pytest.raises(HTTPException) as exc:
        await get_cleaning_plan(uuid.uuid4(), _other_user(), _db_returns_none())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_verification_is_not_visible_cross_user():
    with pytest.raises(HTTPException) as exc:
        await get_verification_report(uuid.uuid4(), _other_user(), _db_returns_none())
    assert exc.value.status_code == 404
