"""Unit tests for the Clerk webhook auth router."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.auth import _verify_webhook_signature, clerk_webhook

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    raw = json.dumps(body).encode()
    req = AsyncMock()
    req.body = AsyncMock(return_value=raw)
    req.json = AsyncMock(return_value=body)
    return req


def _make_db(existing_user: object = None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_user
    db.execute.return_value = result
    db.add = MagicMock()  # SQLAlchemy add() is synchronous
    return db


def _make_user(clerk_id: str = CLERK_ID, email: str = "old@example.com") -> MagicMock:
    u = MagicMock()
    u.clerk_id = clerk_id
    u.email = email
    return u


async def _webhook(body: dict, db: AsyncMock, *, sig: str | None = None) -> dict:
    """Helper: call clerk_webhook with no sig check (CLERK_SECRET_KEY='')."""
    with patch("app.routers.auth.settings") as mock_settings:
        mock_settings.CLERK_SECRET_KEY = ""
        return await clerk_webhook(
            request=_make_request(body),
            db=db,
            svix_id=None,
            svix_timestamp=None,
            svix_signature=sig,
        )


# ---------------------------------------------------------------------------
# _verify_webhook_signature
# ---------------------------------------------------------------------------


class TestVerifyWebhookSignature:
    def test_correct_signature_returns_true(self):
        payload = b'{"type":"user.created"}'
        secret = "test-secret"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert _verify_webhook_signature(payload, sig, secret) is True

    def test_wrong_signature_returns_false(self):
        assert _verify_webhook_signature(b"payload", "wrong", "test-secret") is False

    def test_none_signature_returns_false(self):
        assert _verify_webhook_signature(b"payload", None, "test-secret") is False

    def test_empty_secret_returns_false(self):
        assert _verify_webhook_signature(b"payload", "any-sig", "") is False

    def test_svix_prefixed_v1_signature_verified(self):
        """Svix sends 'v1,<hex>' format; the code strips the prefix."""
        payload = b'{"type":"user.created"}'
        secret = "test-secret"
        hex_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert _verify_webhook_signature(payload, f"v1,{hex_sig}", secret) is True

    def test_multiple_space_separated_signatures(self):
        """Svix may include multiple signatures; any valid one is accepted."""
        payload = b"data"
        secret = "sec"
        good = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert _verify_webhook_signature(payload, f"v1,bad {good}", secret) is True


# ---------------------------------------------------------------------------
# clerk_webhook — event handling
# ---------------------------------------------------------------------------


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
        """Second user.created for the same clerk_id should not duplicate."""
        db = _make_db(existing_user=_make_user())
        response = await _webhook({"type": "user.created", "data": _email_data()}, db)

        assert response == {"status": "ok"}
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_extracts_primary_email(self):
        """User created with the correct primary email address."""
        from app.models.user import User

        db = _make_db(existing_user=None)
        await _webhook({"type": "user.created", "data": _email_data(email="primary@example.com")}, db)

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


# ---------------------------------------------------------------------------
# clerk_webhook — error cases
# ---------------------------------------------------------------------------


class TestClerkWebhookErrors:
    @pytest.mark.asyncio
    async def test_missing_clerk_id_raises_400(self):
        db = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            await _webhook({"type": "user.created", "data": {}}, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_ok(self):
        db = _make_db()
        response = await _webhook({"type": "session.created", "data": {"id": CLERK_ID}}, db)

        assert response == {"status": "ok"}
        db.add.assert_not_called()
        db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self):
        body = {"type": "user.created", "data": _email_data()}
        with patch("app.routers.auth.settings") as mock_settings:
            mock_settings.CLERK_SECRET_KEY = "real-secret"
            with pytest.raises(HTTPException) as exc_info:
                await clerk_webhook(
                    request=_make_request(body),
                    db=_make_db(),
                    svix_id="svix-id",
                    svix_timestamp="123456",
                    svix_signature="v1,wrong-hex-signature",
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_signature_passes_auth(self):
        body = {"type": "user.created", "data": _email_data()}
        raw = json.dumps(body).encode()
        secret = "real-secret"
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

        db = _make_db(existing_user=None)
        with patch("app.routers.auth.settings") as mock_settings:
            mock_settings.CLERK_SECRET_KEY = secret
            response = await clerk_webhook(
                request=_make_request(body),
                db=db,
                svix_id="svix-id",
                svix_timestamp="123456",
                svix_signature=sig,
            )

        assert response == {"status": "ok"}
