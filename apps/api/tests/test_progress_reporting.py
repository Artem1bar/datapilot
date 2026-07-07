"""Tests for the shared progress reporter (Job row + Redis pub/sub)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.tasks import _progress
from app.tasks._progress import publish_progress_sync

JOB_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _reset_redis_client():
    """The Redis client is cached per process — isolate it between tests."""
    _progress._redis_client = None
    yield
    _progress._redis_client = None


def _mock_session_cls(mock_session_cls: MagicMock) -> MagicMock:
    session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
    return session


@patch("app.tasks._progress.redis")
@patch("app.tasks._progress.Session")
@patch("app.tasks._progress.get_sync_engine")
def test_persists_progress_and_publishes(mock_engine, mock_session_cls, mock_redis):
    session = _mock_session_cls(mock_session_cls)

    publish_progress_sync(JOB_ID, "running", 42, "halfway")

    session.execute.assert_called_once()
    session.commit.assert_called_once()

    publish = mock_redis.from_url.return_value.publish
    publish.assert_called_once()
    channel, payload = publish.call_args.args
    assert channel == f"job:{JOB_ID}:progress"
    data = json.loads(payload)
    assert data["progress"] == 42
    assert data["status"] == "running"
    assert data["message"] == "halfway"


@patch("app.tasks._progress.redis")
@patch("app.tasks._progress.get_sync_engine", side_effect=RuntimeError("db down"))
def test_db_failure_does_not_block_publish(mock_engine, mock_redis):
    publish_progress_sync(JOB_ID, "running", 10)

    mock_redis.from_url.return_value.publish.assert_called_once()


@patch("app.tasks._progress.redis")
@patch("app.tasks._progress.Session")
@patch("app.tasks._progress.get_sync_engine")
def test_redis_failure_does_not_raise(mock_engine, mock_session_cls, mock_redis):
    _mock_session_cls(mock_session_cls)
    mock_redis.from_url.side_effect = ConnectionError("no redis")

    publish_progress_sync(JOB_ID, "completed", 100)  # must not raise
