"""The three open AI endpoints (chat, manipulation-parse, dictionary) are
rate-limited before doing any work, matching cleaning/recipes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.analysis import chat
from app.routers.dictionary import get_data_dictionary
from app.routers.manipulation import parse_command


def _user() -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    return u


@pytest.mark.asyncio
async def test_chat_is_rate_limited_before_db_access():
    db = AsyncMock()
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as rl:
        rl.side_effect = HTTPException(status_code=429, detail="rate limited")
        with pytest.raises(HTTPException) as exc:
            await chat(uuid.uuid4(), MagicMock(), _user(), db)
    assert exc.value.status_code == 429
    rl.assert_awaited_once()
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_manipulation_parse_is_rate_limited():
    db = AsyncMock()
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as rl:
        rl.side_effect = HTTPException(status_code=429, detail="rate limited")
        with pytest.raises(HTTPException) as exc:
            await parse_command(uuid.uuid4(), MagicMock(), _user(), db)
    assert exc.value.status_code == 429
    rl.assert_awaited_once()


@pytest.mark.asyncio
async def test_dictionary_is_rate_limited_before_db_access():
    db = AsyncMock()
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as rl:
        rl.side_effect = HTTPException(status_code=429, detail="rate limited")
        with pytest.raises(HTTPException) as exc:
            await get_data_dictionary(uuid.uuid4(), _user(), db)
    assert exc.value.status_code == 429
    rl.assert_awaited_once()
    db.execute.assert_not_called()
