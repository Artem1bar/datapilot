"""User settings (preferences) endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.deps import CurrentUser, DBSession
from app.schemas.settings import UserPreferences, merge_preferences

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])


@router.get("/", response_model=UserPreferences)
async def get_settings(user: CurrentUser) -> UserPreferences:
    """Return the current user's preferences, filled with defaults."""
    return merge_preferences(user.preferences)


@router.put("/", response_model=UserPreferences)
async def update_settings(
    body: dict[str, Any],
    user: CurrentUser,
    db: DBSession,
) -> UserPreferences:
    """Merge a partial preferences update over the current values and persist."""
    unknown = set(body) - set(UserPreferences.model_fields)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown preference key(s): {', '.join(sorted(unknown))}",
        )

    current = merge_preferences(user.preferences)
    merged = {**current.model_dump(), **body}
    try:
        validated = UserPreferences(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    user.preferences = validated.model_dump()
    await db.commit()
    logger.info("Updated preferences for user %s (%d keys changed)", user.id, len(body))
    return validated
