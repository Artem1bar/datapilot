"""Celery tasks: periodic storage-lifecycle cleanup + stale-job reaping."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_sync_engine():
    from app.tasks._db import get_sync_engine

    return get_sync_engine()


@celery_app.task(name="cleanup_orphaned_storage")
def cleanup_orphaned_storage(min_age_hours: int = 24) -> dict:
    """Delete uploaded objects that nothing references (crashed uploads).

    Only touches the ``uploads/`` prefix, and only objects older than
    *min_age_hours*, so an in-flight upload whose DB row hasn't been written
    yet is never removed. Both dataset originals and cleaned outputs live
    under ``uploads/`` — cleaned keys derive from the upload key and are
    referenced from clean jobs, so those references count too.
    """
    from app.models.dataset import Dataset
    from app.models.job import Job
    from app.services.storage import delete_object, list_object_keys

    cutoff = datetime.now(UTC) - timedelta(hours=min_age_hours)

    engine = _get_sync_engine()
    with Session(engine) as session:
        referenced = {k for (k,) in session.execute(select(Dataset.r2_key)).all()}
        # Cleaned outputs also live under uploads/ (their key derives from the
        # upload key) and are referenced from clean jobs, not datasets.
        for (result_json,) in session.execute(
            select(Job.result_json).where(Job.type == "clean", Job.result_json.isnot(None))
        ).all():
            cleaned_key = (result_json or {}).get("cleaned_r2_key")
            if cleaned_key:
                referenced.add(cleaned_key)

    scanned = 0
    deleted = 0
    for key, last_modified in list_object_keys(prefix="uploads/"):
        scanned += 1
        if key in referenced or last_modified > cutoff:
            continue
        delete_object(key)
        deleted += 1
        logger.info("Purged orphaned upload %s", key)

    logger.info("Storage cleanup: scanned=%d deleted=%d", scanned, deleted)
    return {"scanned": scanned, "deleted": deleted}


@celery_app.task(name="purge_expired_exports")
def purge_expired_exports(max_age_days: int = 7) -> dict:
    """Delete export files older than *max_age_days*.

    Exports are one-off downloads written under ``exports/``; nothing in the
    database references them after the job completes, so age is the only
    retention signal.
    """
    from app.services.storage import delete_object, list_object_keys

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

    scanned = 0
    deleted = 0
    for key, last_modified in list_object_keys(prefix="exports/"):
        scanned += 1
        if last_modified >= cutoff:
            continue
        delete_object(key)
        deleted += 1
        logger.info("Purged expired export %s", key)

    logger.info("Export retention: scanned=%d deleted=%d", scanned, deleted)
    return {"scanned": scanned, "deleted": deleted}


_STALE_JOB_MESSAGE = (
    "This job was interrupted (a worker restarted while it was running). Please try again."
)


@celery_app.task(name="reap_stale_jobs")
def reap_stale_jobs(max_age_minutes: int = 30) -> dict:
    """Fail jobs stuck in pending/running long past any plausible runtime.

    If a worker dies mid-task (crash, deploy restart), the queued message is
    lost but the Job row stays pending/running forever and clients poll until
    they time out. Compare against the database clock (``func.now()``) —
    ``created_at`` is written by a DB-side default, so mixing in the app
    server's clock/timezone here would misfire.
    """
    from sqlalchemy import func, update

    from app.models.job import Job

    engine = _get_sync_engine()
    with Session(engine) as session:
        result = session.execute(
            update(Job)
            .where(
                Job.status.in_(("pending", "running")),
                Job.created_at < func.now() - timedelta(minutes=max_age_minutes),
            )
            .values(
                status="failed",
                error_text=_STALE_JOB_MESSAGE,
                completed_at=func.now(),
            )
        )
        session.commit()
        reaped = int(result.rowcount or 0)

    if reaped:
        logger.warning("Reaped %d stale job(s) stuck in pending/running", reaped)
    return {"reaped": reaped}
