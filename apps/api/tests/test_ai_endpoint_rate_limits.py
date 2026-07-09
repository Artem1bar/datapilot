"""The three open AI endpoints (chat, manipulation-parse, dictionary) are
rate-limited before doing any work, matching cleaning/recipes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.analysis import chat
from app.routers.dictionary import get_data_dictionary
from app.routers.manipulation import parse_command

# make_user / mock_db come from conftest.py


@pytest.mark.asyncio
async def test_chat_is_rate_limited_before_db_access(
    make_user: Callable[..., MagicMock], mock_db: AsyncMock
):
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as rl:
        rl.side_effect = HTTPException(status_code=429, detail="rate limited")
        with pytest.raises(HTTPException) as exc:
            await chat(uuid.uuid4(), MagicMock(), make_user(), mock_db)
    assert exc.value.status_code == 429
    rl.assert_awaited_once()
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_manipulation_parse_is_rate_limited(
    make_user: Callable[..., MagicMock], mock_db: AsyncMock
):
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as rl:
        rl.side_effect = HTTPException(status_code=429, detail="rate limited")
        with pytest.raises(HTTPException) as exc:
            await parse_command(uuid.uuid4(), MagicMock(), make_user(), mock_db)
    assert exc.value.status_code == 429
    rl.assert_awaited_once()


@pytest.mark.asyncio
async def test_dictionary_is_rate_limited_before_db_access(
    make_user: Callable[..., MagicMock], mock_db: AsyncMock
):
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as rl:
        rl.side_effect = HTTPException(status_code=429, detail="rate limited")
        with pytest.raises(HTTPException) as exc:
            await get_data_dictionary(uuid.uuid4(), make_user(), mock_db)
    assert exc.value.status_code == 429
    rl.assert_awaited_once()
    mock_db.execute.assert_not_called()
