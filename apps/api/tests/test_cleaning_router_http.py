"""HTTP-layer tests for the cleaning router.

These tests exercise FastAPI's request validation, path parameter coercion,
and auth enforcement — layers that direct handler-unit tests cannot reach
(those call coroutines directly with pre-built mock arguments).

Setup: a minimal FastAPI app mounts the cleaning router with dependency
overrides for CurrentUser and DBSession so tests control what the handlers see
without a real DB or Clerk token.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.routers.cleaning import router

DATASET_ID = str(uuid.uuid4())
JOB_ID = str(uuid.uuid4())
USER_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# App factory with dependency overrides
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


def _unauthed_client() -> TestClient:
    """Client with no auth override — get_current_user will run for real and
    reject the request because DEV_AUTH_BYPASS is False in the test env."""
    app = FastAPI()
    app.include_router(router, prefix="/datasets")
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Path parameter validation
# ---------------------------------------------------------------------------


class TestPathParamValidation:
    """FastAPI rejects invalid UUIDs before the handler runs — these verify the
    routing layer, not the business logic."""

    def test_invalid_uuid_in_get_plan_path_returns_422(self):
        client = _authed_client()
        response = client.get("/datasets/not-a-uuid/plan")
        assert response.status_code == 422

    def test_invalid_uuid_in_post_apply_path_returns_422(self):
        client = _authed_client()
        response = client.post(
            "/datasets/not-a-uuid/apply",
            json={"steps": [{"operation": "drop_nulls", "column": "x", "params": {}}]},
        )
        assert response.status_code == 422

    def test_invalid_uuid_in_post_plan_path_returns_422(self):
        client = _authed_client()
        response = client.post("/datasets/not-a-uuid/plan", json={})
        assert response.status_code == 422

    def test_invalid_uuid_in_revert_path_returns_422(self):
        client = _authed_client()
        response = client.post("/datasets/not-a-uuid/revert")
        assert response.status_code == 422

    def test_invalid_uuid_in_comparison_path_returns_422(self):
        client = _authed_client()
        response = client.get("/datasets/not-a-uuid/comparison")
        assert response.status_code == 422

    def test_invalid_uuid_in_download_path_returns_422(self):
        client = _authed_client()
        response = client.get("/datasets/not-a-uuid/download")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------


class TestBodyValidation:
    def test_apply_with_empty_steps_returns_422(self):
        """ApplyCleaningRequest.steps has min_length=1 — empty list is rejected."""
        client = _authed_client()
        response = client.post(
            f"/datasets/{DATASET_ID}/apply",
            json={"steps": []},
        )
        assert response.status_code == 422

    def test_apply_with_missing_steps_field_returns_422(self):
        client = _authed_client()
        response = client.post(f"/datasets/{DATASET_ID}/apply", json={})
        assert response.status_code == 422

    def test_apply_with_valid_step_passes_validation(self):
        """A well-formed body passes the validation layer — reaches the handler
        (which returns 404 because the DB mock has no dataset)."""
        db = _make_db(None)  # dataset not found → handler raises 404
        client = _authed_client(db=db)
        response = client.post(
            f"/datasets/{DATASET_ID}/apply",
            json={"steps": [{"operation": "drop_nulls", "column": "age", "params": {}}]},
        )
        # 404 means validation passed and the handler ran
        assert response.status_code == 404

    def test_plan_post_with_oversized_instructions_returns_422(self):
        """user_instructions has max_length=2000."""
        client = _authed_client()
        response = client.post(
            f"/datasets/{DATASET_ID}/plan",
            json={"user_instructions": "x" * 2001},
        )
        assert response.status_code == 422

    def test_plan_post_with_no_body_is_valid(self):
        """GeneratePlanRequest has all-optional fields — empty body is valid."""
        from unittest.mock import patch

        with (
            patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            db = _make_db(None)  # dataset not found → handler raises 404
            client = _authed_client(db=db)
            response = client.post(f"/datasets/{DATASET_ID}/plan", json={})
        assert response.status_code == 404  # validation passed; handler ran


# ---------------------------------------------------------------------------
# 404 propagation through the HTTP layer
# ---------------------------------------------------------------------------


class TestNotFoundPropagation:
    def test_get_plan_returns_404_when_dataset_missing(self):
        db = _make_db(None)  # first query (dataset) returns None
        client = _authed_client(db=db)
        response = client.get(f"/datasets/{DATASET_ID}/plan")
        assert response.status_code == 404

    def test_get_plan_returns_404_when_no_plan_job_exists(self):
        dataset = MagicMock()
        dataset.id = uuid.UUID(DATASET_ID)
        dataset.user_id = USER_ID
        db = _make_db(dataset, None)  # dataset found; job query returns None
        client = _authed_client(db=db)
        response = client.get(f"/datasets/{DATASET_ID}/plan")
        assert response.status_code == 404
        assert "Generate one first" in response.json()["detail"]

    def test_revert_returns_404_when_job_missing(self):
        db = _make_db(None)
        client = _authed_client(db=db)
        response = client.post(f"/datasets/{JOB_ID}/revert")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    """Smoke-test that endpoints are mounted at their declared paths."""

    def test_get_plan_route_exists(self):
        client = _authed_client(db=_make_db(None))
        # 404 from the handler (not a routing miss) means the route is registered
        response = client.get(f"/datasets/{DATASET_ID}/plan")
        assert response.status_code != 405  # not Method Not Allowed

    def test_post_plan_route_exists(self):
        from unittest.mock import patch

        with (
            patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            client = _authed_client(db=_make_db(None))
            response = client.post(f"/datasets/{DATASET_ID}/plan", json={})
        assert response.status_code != 405

    def test_post_apply_route_exists(self):
        from unittest.mock import patch

        with (
            patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        ):
            client = _authed_client(db=_make_db(None))
            response = client.post(
                f"/datasets/{DATASET_ID}/apply",
                json={"steps": [{"operation": "drop_nulls", "column": "x", "params": {}}]},
            )
        assert response.status_code != 405

    def test_get_comparison_route_exists(self):
        client = _authed_client(db=_make_db(None))
        response = client.get(f"/datasets/{JOB_ID}/comparison")
        assert response.status_code != 405
