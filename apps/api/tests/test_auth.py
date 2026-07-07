"""Unit tests for the Clerk webhook auth router (svix-verified, fail-closed)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from svix.webhooks import WebhookVerificationError

from app.routers.auth import clerk_webhook

CLERK_ID = "user_abc123"
EMAIL_ADDR_ID = "ea_1"
PRIMARY_EMAIL = "test@example.com"


def _email_data(clerk_id: str = CLERK_ID, email: str = PRIMARY_EMAIL) -> dict:
    return {
        "id": clerk_id,
        "primary_email_address_id": EMAIL_ADDR_ID,
        "email_addresses": [{"id": EMAIL_ADDR_ID, "email_address": email}],
    }


def _make_request(body: dict) -> AsyncMock:
    req = AsyncMock()
    req.body = AsyncMock(return_value=json.dumps(body).encode())
    return req


def _make_db(existing_user: object = None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_user
    db.execute.return_value = result
    db.add = MagicMock()
    return db


def _make_user(clerk_id: str = CLERK_ID, email: str = "old@example.com") -> MagicMock:
    u = MagicMock()
    u.clerk_id = clerk_id
    u.email = email
    return u


async def _webhook(body: dict, db: AsyncMock) -> dict:
    """Call clerk_webhook with svix verification stubbed to return the body."""
    with (
        patch("app.routers.auth.settings") as ms,
        patch("app.routers.auth.Webhook") as mock_webhook,
    ):
        ms.CLERK_WEBHOOK_SECRET = "whsec_test"
        mock_webhook.return_value.verify.return_value = body
        return await clerk_webhook(
            request=_make_request(body),
            db=db,
            svix_id="id",
            svix_timestamp="ts",
            svix_signature="v1,sig",
        )


# ── Verification / security ───────────────────────────────────────────────


class TestWebhookVerification:
    @pytest.mark.asyncio
    async def test_missing_secret_fails_closed(self):
        with patch("app.routers.auth.settings") as ms:
            ms.CLERK_WEBHOOK_SECRET = ""
            with pytest.raises(HTTPException) as exc:
                await clerk_webhook(
                    request=_make_request({"type": "user.created"}),
                    db=_make_db(),
                    svix_id="id",
                    svix_timestamp="ts",
                    svix_signature="sig",
                )
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self):
        with (
            patch("app.routers.auth.settings") as ms,
            patch("app.routers.auth.Webhook") as mock_webhook,
        ):
            ms.CLERK_WEBHOOK_SECRET = "whsec_test"
            mock_webhook.return_value.verify.side_effect = WebhookVerificationError("bad")
            with pytest.raises(HTTPException) as exc:
                await clerk_webhook(
                    request=_make_request({"type": "user.created"}),
                    db=_make_db(),
                    svix_id="id",
                    svix_timestamp="ts",
                    svix_signature="v1,wrong",
                )
        assert exc.value.status_code == 401


# ── Event handling ────────────────────────────────────────────────────────


class TestClerkWebhookUserCreated:
    @pytest.mark.asyncio
    async def test_creates_new_user(self):
        db = _make_db(existing_user=None)
        response = await _webhook({"type": "user.created", "data": _email_data()}, db)
        assert response == {"status": "ok"}
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotent_when_user_already_exists(self):
        db = _make_db(existing_user=_make_user())
        response = await _webhook({"type": "user.created", "data": _email_data()}, db)
        assert response == {"status": "ok"}
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_extracts_primary_email(self):
        from app.models.user import User

        db = _make_db(existing_user=None)
        await _webhook(
            {"type": "user.created", "data": _email_data(email="primary@example.com")}, db
        )
        added = db.add.call_args[0][0]
        assert isinstance(added, User)
        assert added.email == "primary@example.com"


class TestClerkWebhookUserUpdated:
    @pytest.mark.asyncio
    async def test_updates_email(self):
        user = _make_user(email="old@example.com")
        db = _make_db(existing_user=user)
        await _webhook({"type": "user.updated", "data": _email_data(email="new@example.com")}, db)
        assert user.email == "new@example.com"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_when_user_not_found(self):
        db = _make_db(existing_user=None)
        response = await _webhook({"type": "user.updated", "data": _email_data()}, db)
        assert response == {"status": "ok"}
        db.commit.assert_not_awaited()


class TestClerkWebhookUserDeleted:
    @pytest.mark.asyncio
    async def test_deletes_existing_user(self):
        user = _make_user()
        db = _make_db(existing_user=user)
        response = await _webhook({"type": "user.deleted", "data": {"id": CLERK_ID}}, db)
        assert response == {"status": "ok"}
        db.delete.assert_awaited_once_with(user)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_when_user_not_found(self):
        db = _make_db(existing_user=None)
        response = await _webhook({"type": "user.deleted", "data": {"id": CLERK_ID}}, db)
        assert response == {"status": "ok"}
        db.delete.assert_not_awaited()


class TestClerkWebhookErrors:
    @pytest.mark.asyncio
    async def test_missing_clerk_id_raises_400(self):
        db = _make_db()
        with pytest.raises(HTTPException) as exc:
            await _webhook({"type": "user.created", "data": {}}, db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_ok(self):
        db = _make_db()
        response = await _webhook({"type": "session.created", "data": {"id": CLERK_ID}}, db)
        assert response == {"status": "ok"}
        db.add.assert_not_called()
        db.delete.assert_not_awaited()
