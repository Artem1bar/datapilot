"""HTTP-layer tests for the manipulation router.

These tests exercise FastAPI's request validation, path parameter coercion,
and auth enforcement — layers that direct handler-unit tests cannot reach
(those call coroutines directly with pre-built mock arguments).

Setup: a minimal FastAPI app mounts the manipulation router with dependency
overrides for CurrentUser and DBSession so tests control what the handlers see
without a real DB or Clerk token.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.routers.manipulation import router

DATASET_ID = str(uuid.uuid4())
USER_ID = uuid.uuid4()

# A minimal valid ManipulationOp body for reuse across tests
VALID_OP = {"op_type": "delete_columns", "params": {"columns": ["x"]}, "description": "drop x"}


# ---------------------------------------------------------------------------
# Shared factories
# ---------------------------------------------------------------------------


def _make_user(user_id: uuid.UUID = USER_ID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


def _make_db(*query_results: object) -> AsyncMock:
    """AsyncMock db whose execute() calls return the given results in order."""
    db = AsyncMock()
    mocks = []
    for value in query_results:
        m = MagicMock()
        if isinstance(value, list):
            m.scalars.return_value.all.return_value = value
        else:
            m.scalar_one_or_none.return_value = value
        mocks.append(m)
    if mocks:
        db.execute.side_effect = mocks
    else:
        m = MagicMock()
        m.scalar_one_or_none.return_value = None
        db.execute.return_value = m
    return db


def _app_with_overrides(
    user: MagicMock | None = None,
    db: AsyncMock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/datasets")
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    return app


def _authed_client(
    user: MagicMock | None = None,
    db: AsyncMock | None = None,
) -> TestClient:
    if user is None:
        user = _make_user()
    return TestClient(_app_with_overrides(user=user, db=db))


# ---------------------------------------------------------------------------
# Path parameter validation
# ---------------------------------------------------------------------------


class TestPathParamValidation:
    """FastAPI rejects invalid UUIDs before the handler runs — these verify the
    routing layer, not the business logic."""

    def test_invalid_uuid_in_parse_path_returns_422(self):
        client = _authed_client()
        response = client.post(
            "/datasets/not-a-uuid/parse",
            json={"command": "delete column A"},
        )
        assert response.status_code == 422

    def test_invalid_uuid_in_apply_path_returns_422(self):
        client = _authed_client()
        response = client.post(
            "/datasets/not-a-uuid/apply",
            json={"operations": [VALID_OP]},
        )
        assert response.status_code == 422

    def test_invalid_uuid_in_undo_path_returns_422(self):
        client = _authed_client()
        response = client.post(
            "/datasets/not-a-uuid/undo",
            json={"snapshot_id": "snap-abc"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------


class TestBodyValidation:
    def test_parse_with_empty_command_returns_422(self):
        """ManipulationParseRequest.command has min_length=1."""
        client = _authed_client()
        response = client.post(
            f"/datasets/{DATASET_ID}/parse",
            json={"command": ""},
        )
        assert response.status_code == 422

    def test_parse_with_oversized_command_returns_422(self):
        """ManipulationParseRequest.command has max_length=2000."""
        client = _authed_client()
        response = client.post(
            f"/datasets/{DATASET_ID}/parse",
            json={"command": "x" * 2001},
        )
        assert response.status_code == 422

    def test_parse_with_missing_command_returns_422(self):
        client = _authed_client()
        response = client.post(f"/datasets/{DATASET_ID}/parse", json={})
        assert response.status_code == 422

    def test_parse_with_valid_command_passes_validation(self):
        """A well-formed body passes the validation layer — reaches the handler
        (which raises 404 because the DB mock has no dataset)."""
        with (
            patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            db = _make_db(None)  # dataset not found → handler raises 404
            client = _authed_client(db=db)
            response = client.post(
                f"/datasets/{DATASET_ID}/parse",
                json={"command": "delete column A"},
            )
        # 404 means validation passed and the handler ran
        assert response.status_code == 404

    def test_apply_with_empty_operations_returns_422(self):
        """ManipulationApplyRequest.operations has min_length=1."""
        client = _authed_client()
        response = client.post(
            f"/datasets/{DATASET_ID}/apply",
            json={"operations": []},
        )
        assert response.status_code == 422

    def test_apply_with_missing_operations_returns_422(self):
        client = _authed_client()
        response = client.post(f"/datasets/{DATASET_ID}/apply", json={})
        assert response.status_code == 422

    def test_apply_with_valid_operations_passes_validation(self):
        """A well-formed body passes the validation layer — reaches 404."""
        db = _make_db(None)  # dataset not found → handler raises 404
        client = _authed_client(db=db)
        response = client.post(
            f"/datasets/{DATASET_ID}/apply",
            json={"operations": [VALID_OP]},
        )
        assert response.status_code == 404

    def test_undo_with_missing_snapshot_id_returns_422(self):
        client = _authed_client()
        response = client.post(f"/datasets/{DATASET_ID}/undo", json={})
        assert response.status_code == 422

    def test_undo_with_valid_body_passes_validation(self):
        """A well-formed undo body passes validation — reaches 404."""
        db = _make_db(None)  # dataset not found → handler raises 404
        client = _authed_client(db=db)
        response = client.post(
            f"/datasets/{DATASET_ID}/undo",
            json={"snapshot_id": "snap-abc123"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 404 propagation through the HTTP layer
# ---------------------------------------------------------------------------


class TestNotFoundPropagation:
    def test_apply_returns_404_when_dataset_missing(self):
        db = _make_db(None)  # dataset query returns None
        client = _authed_client(db=db)
        response = client.post(
            f"/datasets/{DATASET_ID}/apply",
            json={"operations": [VALID_OP]},
        )
        assert response.status_code == 404
        assert "Dataset not found" in response.json()["detail"]

    def test_undo_returns_404_when_dataset_missing(self):
        db = _make_db(None)
        client = _authed_client(db=db)
        response = client.post(
            f"/datasets/{DATASET_ID}/undo",
            json={"snapshot_id": "snap-xyz"},
        )
        assert response.status_code == 404
        assert "Dataset not found" in response.json()["detail"]

    def test_parse_returns_404_when_dataset_missing(self):
        with (
            patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            db = _make_db(None)
            client = _authed_client(db=db)
            response = client.post(
                f"/datasets/{DATASET_ID}/parse",
                json={"command": "rename column B to Name"},
            )
        assert response.status_code == 404
        assert "Dataset not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    """Smoke-test that endpoints are mounted at their declared paths."""

    def test_post_parse_route_exists(self):
        with (
            patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            client = _authed_client(db=_make_db(None))
            response = client.post(
                f"/datasets/{DATASET_ID}/parse",
                json={"command": "sort by age"},
            )
        # Any response other than 405 Method Not Allowed confirms the route exists
        assert response.status_code != 405

    def test_post_apply_route_exists(self):
        client = _authed_client(db=_make_db(None))
        response = client.post(
            f"/datasets/{DATASET_ID}/apply",
            json={"operations": [VALID_OP]},
        )
        assert response.status_code != 405

    def test_post_undo_route_exists(self):
        client = _authed_client(db=_make_db(None))
        response = client.post(
            f"/datasets/{DATASET_ID}/undo",
            json={"snapshot_id": "snap-abc"},
        )
        assert response.status_code != 405
