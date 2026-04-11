"""FastAPI dependencies: DB session, current user (dev mode – no auth required)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.models.user import User

# Fixed dev user constants
DEV_CLERK_ID = "dev_user_local"
DEV_EMAIL = "dev@datapilot.local"


async def get_current_user(
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return a default dev user, creating one if it doesn't exist.

    No Authorization header is required. This is a simplified dependency
    for local development without Clerk.
    """
    result = await db.execute(select(User).where(User.clerk_id == DEV_CLERK_ID))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=uuid.uuid4(),
            clerk_id=DEV_CLERK_ID,
            email=DEV_EMAIL,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user


# Typed dependency shortcuts – same exports as before
CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
