"""Storage-lifecycle cleanup: orphan purge + object listing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.tasks.cleanup_task import cleanup_orphaned_storage


def test_purges_only_unreferenced_objects_older_than_cutoff():
    now = datetime.now(UTC)
    old = now - timedelta(hours=48)
    recent = now - timedelta(hours=1)

    listing = [
        ("uploads/u/keep.csv", old),  # referenced → keep
        ("uploads/u/orphan_old.csv", old),  # unreferenced + old → delete
        ("uploads/u/orphan_new.csv", recent),  # unreferenced but too new → keep
    ]

    session = MagicMock()
    dataset_keys = MagicMock()
    dataset_keys.all.return_value = [("uploads/u/keep.csv",)]
    job_results = MagicMock()
    job_results.all.return_value = []
    session.execute.side_effect = [dataset_keys, job_results]
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session

    with (
        patch("app.tasks.cleanup_task._get_sync_engine", return_value=MagicMock()),
        patch("app.tasks.cleanup_task.Session", return_value=session_cm),
        patch("app.services.storage.list_object_keys", return_value=listing),
        patch("app.services.storage.delete_object") as mock_delete,
    ):
        result = cleanup_orphaned_storage(min_age_hours=24)

    assert result == {"scanned": 3, "deleted": 1}
    mock_delete.assert_called_once_with("uploads/u/orphan_old.csv")


def test_list_object_keys_paginates_and_skips_empty_pages():
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "uploads/a", "LastModified": "t1"}]},
        {"Contents": [{"Key": "uploads/b", "LastModified": "t2"}]},
        {},  # empty page — no Contents
    ]
    client.get_paginator.return_value = paginator

    with patch("app.services.storage.get_s3_client", return_value=client):
        from app.services.storage import list_object_keys

        keys = list_object_keys("uploads/")

    assert keys == [("uploads/a", "t1"), ("uploads/b", "t2")]


def test_cleaned_files_are_protected_from_orphan_purge():
    """Cleaned outputs live under uploads/ too (their key derives from the
    upload key) but are referenced from clean jobs, not datasets. The purge
    must treat them as referenced (live QA find, 2026-07-09)."""
    now = datetime.now(UTC)
    old = now - timedelta(hours=48)

    listing = [
        ("uploads/u/data.csv", old),  # referenced by dataset → keep
        ("uploads/u/data_cleaned_abc123.csv", old),  # referenced by clean job → keep
        ("uploads/u/orphan.csv", old),  # truly orphaned → delete
    ]

    session = MagicMock()
    dataset_keys = MagicMock()
    dataset_keys.all.return_value = [("uploads/u/data.csv",)]
    job_results = MagicMock()
    job_results.all.return_value = [
        ({"cleaned_r2_key": "uploads/u/data_cleaned_abc123.csv"},),
        (None,),
    ]
    session.execute.side_effect = [dataset_keys, job_results]
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session

    with (
        patch("app.tasks.cleanup_task._get_sync_engine", return_value=MagicMock()),
        patch("app.tasks.cleanup_task.Session", return_value=session_cm),
        patch("app.services.storage.list_object_keys", return_value=listing),
        patch("app.services.storage.delete_object") as mock_delete,
    ):
        result = cleanup_orphaned_storage(min_age_hours=24)

    assert result == {"scanned": 3, "deleted": 1}
    mock_delete.assert_called_once_with("uploads/u/orphan.csv")


def test_purge_expired_exports_deletes_only_old_objects():
    from app.tasks.cleanup_task import purge_expired_exports

    now = datetime.now(UTC)
    listing = [
        ("exports/d1/old.csv", now - timedelta(days=10)),
        ("exports/d1/fresh.csv", now - timedelta(hours=2)),
    ]
    with (
        patch("app.services.storage.list_object_keys", return_value=listing),
        patch("app.services.storage.delete_object") as mock_delete,
    ):
        result = purge_expired_exports(max_age_days=7)

    assert result == {"scanned": 2, "deleted": 1}
    mock_delete.assert_called_once_with("exports/d1/old.csv")


def test_reap_stale_jobs_fails_stuck_jobs():
    from app.tasks.cleanup_task import reap_stale_jobs

    session = MagicMock()
    session.execute.return_value.rowcount = 2
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session

    with (
        patch("app.tasks.cleanup_task._get_sync_engine", return_value=MagicMock()),
        patch("app.tasks.cleanup_task.Session", return_value=session_cm),
    ):
        result = reap_stale_jobs(max_age_minutes=30)

    assert result == {"reaped": 2}
    session.commit.assert_called_once()
