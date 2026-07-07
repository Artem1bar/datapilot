"""Clerk session-JWT verification via JWKS.

Verifies the RS256 session token minted by Clerk against the public keys
published at ``{CLERK_JWT_ISSUER}/.well-known/jwks.json``. Keys are cached and
refreshed once on a verification miss (to survive key rotation).
"""

from __future__ import annotations

import logging

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

logger = logging.getLogger(__name__)

_jwks_cache: dict | None = None


class ClerkAuthError(Exception):
    """Raised when a Clerk token cannot be verified."""


def _issuer() -> str:
    issuer = settings.CLERK_JWT_ISSUER.rstrip("/")
    if not issuer:
        raise ClerkAuthError("CLERK_JWT_ISSUER is not configured")
    return issuer


def _get_jwks(force_refresh: bool = False) -> dict:
    global _jwks_cache
    if _jwks_cache is None or force_refresh:
        resp = httpx.get(f"{_issuer()}/.well-known/jwks.json", timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
    return _jwks_cache


def _key_for(token: str, jwks: dict) -> dict:
    kid = jwt.get_unverified_header(token).get("kid")
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise ClerkAuthError("no matching JWKS key for token")


def verify_clerk_token(token: str) -> dict:
    """Verify a Clerk session JWT and return its claims (raises ClerkAuthError)."""
    issuer = _issuer()

    def _decode(jwks: dict) -> dict:
        key = _key_for(token, jwks)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=issuer,
            # Clerk session tokens carry no fixed audience.
            options={"verify_aud": False},
        )

    try:
        return _decode(_get_jwks())
    except (ClerkAuthError, JWTError, httpx.HTTPError):
        try:
            return _decode(_get_jwks(force_refresh=True))
        except Exception as exc:  # noqa: BLE001 — normalize to one auth error
            raise ClerkAuthError(f"token verification failed: {exc}") from exc
