"""Clerk JWT verification + the get_current_user dependency (bypass vs. prod)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwk, jwt

import app.services.clerk_auth as clerk_auth
from app.config import settings
from app.deps import DEV_CLERK_ID, get_current_user
from app.services.clerk_auth import ClerkAuthError, verify_clerk_token

ISSUER = "https://test.clerk.accounts.dev"


@pytest.fixture
def rsa_jwks():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_jwk = jwk.construct(pub_pem, "RS256").to_dict()
    pub_jwk["kid"] = "test-kid"
    for k in ("n", "e"):
        if isinstance(pub_jwk.get(k), bytes):
            pub_jwk[k] = pub_jwk[k].decode()
    return priv_pem, {"keys": [pub_jwk]}


def _token(priv_pem, **claims):
    payload = {"sub": "user_123", "iss": ISSUER, **claims}
    return jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": "test-kid"})


# ── verify_clerk_token ────────────────────────────────────────────────────


def test_verify_valid_token(monkeypatch, rsa_jwks):
    priv, jwks = rsa_jwks
    monkeypatch.setattr(settings, "CLERK_JWT_ISSUER", ISSUER)
    clerk_auth._jwks_cache = None
    with patch.object(clerk_auth, "_get_jwks", return_value=jwks):
        claims = verify_clerk_token(_token(priv, email="a@b.com"))
    assert claims["sub"] == "user_123"
    assert claims["email"] == "a@b.com"


def test_verify_rejects_wrong_issuer(monkeypatch, rsa_jwks):
    priv, jwks = rsa_jwks
    monkeypatch.setattr(settings, "CLERK_JWT_ISSUER", ISSUER)
    bad = jwt.encode(
        {"sub": "u", "iss": "https://evil.example"},
        priv,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )
    with patch.object(clerk_auth, "_get_jwks", return_value=jwks):
        with pytest.raises(ClerkAuthError):
            verify_clerk_token(bad)


def test_verify_requires_issuer_configured(monkeypatch):
    monkeypatch.setattr(settings, "CLERK_JWT_ISSUER", "")
    with pytest.raises(ClerkAuthError):
        verify_clerk_token("anything")


# ── get_current_user ──────────────────────────────────────────────────────


def _db_creating() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # user not found → create
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_dev_bypass_returns_dev_user(monkeypatch):
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    db = _db_creating()
    await get_current_user(db=db, authorization=None)
    assert db.add.call_args[0][0].clerk_id == DEV_CLERK_ID


@pytest.mark.asyncio
async def test_production_ignores_bypass_and_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)  # must be ignored
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(db=AsyncMock(), authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_production_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with patch("app.deps.verify_clerk_token", side_effect=ClerkAuthError("bad")):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(db=AsyncMock(), authorization="Bearer xxx")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_production_resolves_user_from_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    db = _db_creating()
    with patch(
        "app.deps.verify_clerk_token",
        return_value={"sub": "clerk_abc", "email": "x@y.com"},
    ):
        await get_current_user(db=db, authorization="Bearer good")
    created = db.add.call_args[0][0]
    assert created.clerk_id == "clerk_abc"
    assert created.email == "x@y.com"
