"""Celery task: periodic storage-lifecycle cleanup."""

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
    """Delete uploaded objects that no dataset references (crashed uploads).

    Only touches the ``uploads/`` prefix, and only objects older than
    *min_age_hours*, so an in-flight upload whose DB row hasn't been written
    yet is never removed. Cleaned files, snapshots, and exports live under
    other prefixes and are intentionally out of scope here.
    """
    from app.models.dataset import Dataset
    from app.services.storage import delete_object, list_object_keys

    cutoff = datetime.now(UTC) - timedelta(hours=min_age_hours)

    engine = _get_sync_engine()
    with Session(engine) as session:
        referenced = {k for (k,) in session.execute(select(Dataset.r2_key)).all()}

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
