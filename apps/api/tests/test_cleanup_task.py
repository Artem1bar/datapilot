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
    session.execute.return_value.all.return_value = [("uploads/u/keep.csv",)]
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
