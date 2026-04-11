"""Clerk webhook handler for user sync events."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.db.engine import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def _verify_webhook_signature(
    payload: bytes,
    signature: str | None,
    secret: str,
) -> bool:
    """Verify the Clerk/Svix webhook signature.

    Clerk uses Svix for webhook delivery. The signature is an HMAC-SHA256
    of the raw body using the webhook signing secret. This is a simplified
    check; a production implementation should use the ``svix`` library for
    full timestamp + signature verification.
    """
    if not signature or not secret:
        return False
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    # Svix sends multiple signatures separated by spaces; check each
    for sig_part in signature.split(" "):
        # Strip the version prefix (e.g. "v1,<base64>")
        clean = sig_part.split(",")[-1] if "," in sig_part else sig_part
        if hmac.compare_digest(expected, clean):
            return True
    return False


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    svix_id: str | None = Header(None, alias="svix-id"),
    svix_timestamp: str | None = Header(None, alias="svix-timestamp"),
    svix_signature: str | None = Header(None, alias="svix-signature"),
) -> dict[str, str]:
    """Handle Clerk webhook events (user.created, user.updated, user.deleted)."""
    body = await request.body()

    # Signature verification placeholder -- in production use the svix library
    # For now we log a warning if we cannot verify
    if settings.CLERK_SECRET_KEY:
        valid = _verify_webhook_signature(body, svix_signature, settings.CLERK_SECRET_KEY)
        if not valid:
            logger.warning("Webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    payload: dict[str, Any] = await request.json()
    event_type: str = payload.get("type", "")
    data: dict[str, Any] = payload.get("data", {})

    clerk_id: str | None = data.get("id")
    if not clerk_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user id in webhook data")

    if event_type == "user.created":
        email = _extract_email(data)
        existing = await db.execute(select(User).where(User.clerk_id == clerk_id))
        if existing.scalar_one_or_none() is None:
            user = User(clerk_id=clerk_id, email=email)
            db.add(user)
            await db.commit()
            logger.info("Created user %s from webhook", clerk_id)

    elif event_type == "user.updated":
        email = _extract_email(data)
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        user = result.scalar_one_or_none()
        if user:
            user.email = email
            await db.commit()
            logger.info("Updated user %s from webhook", clerk_id)

    elif event_type == "user.deleted":
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        user = result.scalar_one_or_none()
        if user:
            await db.delete(user)
            await db.commit()
            logger.info("Deleted user %s from webhook", clerk_id)

    else:
        logger.debug("Ignoring webhook event type: %s", event_type)

    return {"status": "ok"}


def _extract_email(data: dict[str, Any]) -> str:
    """Extract primary email from Clerk webhook user data."""
    email_addresses = data.get("email_addresses", [])
    for addr in email_addresses:
        if addr.get("id") == data.get("primary_email_address_id"):
            return addr.get("email_address", "")
    if email_addresses:
        return email_addresses[0].get("email_address", "")
    return f"{data.get('id', 'unknown')}@clerk.user"
