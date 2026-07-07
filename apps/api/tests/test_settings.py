"""User settings: preferences schema defaults + GET/PUT handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.routers.settings import get_settings, update_settings
from app.schemas.settings import UserPreferences, merge_preferences


def test_preferences_defaults():
    p = UserPreferences()
    assert p.cleaning_aggressiveness == "standard"
    assert p.cap_strategy == "auto"
    assert p.review_first is True
    assert p.max_remediation_rounds == 2
    assert p.domain == "auto"


def test_merge_fills_defaults_and_ignores_unknown_stored_keys():
    p = merge_preferences({"cap_strategy": "off", "legacy_removed_key": 123})
    assert p.cap_strategy == "off"
    assert p.cleaning_aggressiveness == "standard"  # default filled in


@pytest.mark.asyncio
async def test_get_settings_returns_defaults_for_empty_user():
    user = MagicMock()
    user.preferences = {}
    result = await get_settings(user)
    assert result.cap_strategy == "auto"


@pytest.mark.asyncio
async def test_get_settings_reflects_stored_values():
    user = MagicMock()
    user.preferences = {"domain": "survey"}
    result = await get_settings(user)
    assert result.domain == "survey"


@pytest.mark.asyncio
async def test_update_merges_partial_and_persists():
    user = MagicMock()
    user.preferences = {"domain": "survey"}
    user.id = "u1"
    db = AsyncMock()

    result = await update_settings({"cap_strategy": "off"}, user, db)

    assert result.cap_strategy == "off"
    assert result.domain == "survey"  # preserved from prior stored value
    assert user.preferences["cap_strategy"] == "off"  # full blob persisted
    assert user.preferences["domain"] == "survey"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_rejects_unknown_key():
    user = MagicMock()
    user.preferences = {}
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await update_settings({"not_a_real_key": 1}, user, db)
    assert exc.value.status_code == 422
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_update_rejects_invalid_value():
    user = MagicMock()
    user.preferences = {}
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await update_settings({"cap_strategy": "bogus"}, user, db)
    assert exc.value.status_code == 422
    db.commit.assert_not_called()
