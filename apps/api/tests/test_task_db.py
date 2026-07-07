"""Tests for the shared per-process sync engine used by Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks import _db


def _reset() -> None:
    _db._engine = None


def test_engine_is_created_once_and_reused():
    _reset()
    try:
        e1 = _db.get_sync_engine()
        e2 = _db.get_sync_engine()
        assert e1 is e2
    finally:
        _reset()


def test_asyncpg_url_swapped_to_psycopg2(monkeypatch):
    _reset()
    try:
        monkeypatch.setattr(_db.settings, "DATABASE_URL", "postgresql+asyncpg://u@h:5432/db")
        engine = _db.get_sync_engine()
        assert engine.url.drivername == "postgresql+psycopg2"
    finally:
        _reset()


def test_task_helpers_delegate_to_shared_engine():
    from app.tasks.cleaning_task import _get_sync_engine as cleaning_engine
    from app.tasks.export_task import _get_sync_engine as export_engine
    from app.tasks.profile_task import _get_sync_engine as profile_engine

    sentinel = MagicMock()
    with patch("app.tasks._db.get_sync_engine", return_value=sentinel):
        assert cleaning_engine() is sentinel
        assert profile_engine() is sentinel
        assert export_engine() is sentinel
