"""Shared synchronous SQLAlchemy engine for Celery workers.

Tasks previously created a fresh Engine (and connection pool) on every
invocation and never disposed it, slowly leaking Postgres connections.
One engine per worker process, reused across task runs.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import settings

_engine: Engine | None = None


def get_sync_engine() -> Engine:
    """Return the process-wide synchronous engine, creating it on first use."""
    global _engine
    if _engine is None:
        if "asyncpg" in settings.DATABASE_URL:
            sync_url = settings.DATABASE_URL.replace("asyncpg", "psycopg2")
        else:
            sync_url = settings.DATABASE_URL
        _engine = create_engine(sync_url, pool_pre_ping=True)
    return _engine
