"""FastAPI dependencies: DB session and the authenticated current user.

In non-production environments with ``DEV_AUTH_BYPASS`` enabled, every request
resolves to a local dev user (no token needed). Otherwise a verified Clerk
session JWT is required — the bypass is ignored entirely in production.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_db
from app.models.user import User
from app.services.clerk_auth import ClerkAuthError, verify_clerk_token

# Fixed dev user constants
DEV_CLERK_ID = "dev_user_local"
DEV_EMAIL = "dev@datapilot.local"


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def _resolve_or_create_user(db: AsyncSession, clerk_id: str, email: str) -> User:
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=uuid.uuid4(), clerk_id=clerk_id, email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the authenticated user from a Clerk JWT, or the dev user in dev."""
    # Dev bypass — never honored in production.
    if settings.DEV_AUTH_BYPASS and settings.ENVIRONMENT != "production":
        return await _resolve_or_create_user(db, DEV_CLERK_ID, DEV_EMAIL)

    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify_clerk_token(token)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    clerk_id = claims.get("sub")
    if not clerk_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject claim",
        )
    email = claims.get("email") or f"{clerk_id}@clerk.local"
    return await _resolve_or_create_user(db, clerk_id, email)


# Typed dependency shortcuts
CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
