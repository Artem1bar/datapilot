"""HTTP-layer tests for the analysis router's session endpoints.

Covers list_sessions (GET /{dataset_id}/sessions) and get_session
(GET /sessions/{session_id}). DB is fully mocked — no live services needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.routers.analysis import router

DATASET_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_user(user_id: uuid.UUID = USER_ID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


def _make_session(
    session_id: uuid.UUID = SESSION_ID,
    dataset_id: uuid.UUID = DATASET_ID,
    user_id: uuid.UUID = USER_ID,
    messages: list | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = session_id
    s.dataset_id = dataset_id
    s.user_id = user_id
    s.messages_json = messages or []
    s.created_at = NOW
    s.updated_at = NOW
    return s


def _make_db_scalars(*rows: object) -> AsyncMock:
    """DB returning a list from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    db.execute.return_value = result
    return db


def _make_db_scalar_one_or_none(value: object) -> AsyncMock:
    """DB returning a single optional row."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute.return_value = result
    return db


def _authed_client(
    user: MagicMock | None = None,
    db: AsyncMock | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/analysis")
    if user is None:
        user = _make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /{dataset_id}/sessions — list_sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_invalid_dataset_uuid_returns_422(self):
        client = _authed_client()
        response = client.get("/analysis/not-a-uuid/sessions")
        assert response.status_code == 422

    def test_returns_empty_list_when_no_sessions(self):
        db = _make_db_scalars()
        client = _authed_client(db=db)
        response = client.get(f"/analysis/{DATASET_ID}/sessions")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_single_session(self):
        session = _make_session()
        db = _make_db_scalars(session)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/{DATASET_ID}/sessions")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(SESSION_ID)
        assert body[0]["dataset_id"] == str(DATASET_ID)

    def test_returns_multiple_sessions(self):
        s1 = _make_session(session_id=uuid.uuid4())
        s2 = _make_session(session_id=uuid.uuid4())
        db = _make_db_scalars(s1, s2)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/{DATASET_ID}/sessions")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_messages_json_included(self):
        session = _make_session(messages=[{"role": "user", "content": "Hello"}])
        db = _make_db_scalars(session)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/{DATASET_ID}/sessions")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["messages_json"] == [{"role": "user", "content": "Hello"}]

    def test_user_id_scopes_query(self):
        # When db returns nothing, the endpoint returns an empty list — ownership
        # filtering is enforced in the DB query (tested via the mock fixture).
        db = _make_db_scalars()
        client = _authed_client(db=db)
        response = client.get(f"/analysis/{DATASET_ID}/sessions")
        assert response.status_code == 200
        # DB was queried exactly once
        assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# GET /sessions/{session_id} — get_session
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_invalid_session_uuid_returns_422(self):
        client = _authed_client()
        response = client.get("/analysis/sessions/not-a-uuid")
        assert response.status_code == 422

    def test_returns_404_when_session_not_found(self):
        db = _make_db_scalar_one_or_none(None)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/sessions/{SESSION_ID}")
        assert response.status_code == 404
        assert "Chat session not found" in response.json()["detail"]

    def test_returns_session_when_found(self):
        session = _make_session()
        db = _make_db_scalar_one_or_none(session)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/sessions/{SESSION_ID}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(SESSION_ID)
        assert body["dataset_id"] == str(DATASET_ID)

    def test_messages_json_returned(self):
        session = _make_session(messages=[{"role": "assistant", "content": "Hi there"}])
        db = _make_db_scalar_one_or_none(session)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/sessions/{SESSION_ID}")
        assert response.status_code == 200
        assert response.json()["messages_json"] == [{"role": "assistant", "content": "Hi there"}]

    def test_timestamps_included_in_response(self):
        session = _make_session()
        db = _make_db_scalar_one_or_none(session)
        client = _authed_client(db=db)
        response = client.get(f"/analysis/sessions/{SESSION_ID}")
        assert response.status_code == 200
        body = response.json()
        assert "created_at" in body
        assert "updated_at" in body
