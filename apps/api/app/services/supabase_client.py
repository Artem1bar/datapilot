"""Supabase client singleton.

Provides access to Supabase services (Auth, Storage, Realtime) when configured.
Falls back gracefully when SUPABASE_URL is not set (local development with Docker).

Usage:
    from app.services.supabase_client import get_supabase

    supabase = get_supabase()
    if supabase:
        # Use Supabase Auth, Storage, etc.
        user = supabase.auth.get_user(token)
    else:
        # Fallback to local services (Clerk auth, MinIO storage)
        ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_client = None
_initialized = False


def get_supabase():
    """Return a Supabase client or None if not configured.

    Uses the service role key for backend operations (full access).
    """
    global _client, _initialized

    if _initialized:
        return _client

    _initialized = True

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        logger.info("Supabase not configured — using local services (Docker Postgres, MinIO, etc.)")
        return None

    try:
        from supabase import create_client

        _client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,
        )
        logger.info("Supabase client initialized: %s", settings.SUPABASE_URL)
    except ImportError:
        logger.warning(
            "supabase-py not installed. Run: pip install supabase. Falling back to local services."
        )
    except Exception:
        logger.exception("Failed to initialize Supabase client")

    return _client


def is_supabase_configured() -> bool:
    """Check whether Supabase credentials are present in the environment."""
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
