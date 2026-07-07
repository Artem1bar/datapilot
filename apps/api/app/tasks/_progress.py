"""Job progress reporting for Celery tasks.

Persists the progress value on the Job row (so HTTP polling clients see real
per-stage progress) and publishes the full update over Redis pub/sub for any
live subscribers. Both writes are best-effort: progress reporting must never
fail a job.
"""

from __future__ import annotations

import json
import logging
import uuid

import redis
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.tasks._db import get_sync_engine

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    """Return the process-wide Redis client, creating it on first use."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL)
    return _redis_client


def publish_progress_sync(job_id: str, status: str, progress: int, message: str = "") -> None:
    """Record job progress in the DB and broadcast it over Redis pub/sub."""
    try:
        with Session(get_sync_engine()) as session:
            session.execute(
                update(Job).where(Job.id == uuid.UUID(job_id)).values(progress=progress)
            )
            session.commit()
    except Exception as exc:
        logger.warning("Progress DB update failed (non-fatal): %s", exc)

    try:
        r = _get_redis_client()
        payload = json.dumps(
            {
                "job_id": job_id,
                "status": status,
                "progress": progress,
                "message": message,
                "result": None,
            }
        )
        r.publish(f"job:{job_id}:progress", payload)
    except Exception as exc:
        logger.warning("Progress publish failed (non-fatal): %s", exc)
