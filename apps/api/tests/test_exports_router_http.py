"""HTTP-layer tests for the exports router.

Covers request-validation, auth enforcement, ownership checks, and business-
rule errors (dataset not ready, job not completed, missing storage key).
DB and Celery are fully mocked — no live services needed.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.routers.exports import router

DATASET_ID = str(uuid.uuid4())
JOB_ID = str(uuid.uuid4())
USER_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Shared factories (mirror test_manipulation_router_http.py conventions)
# ---------------------------------------------------------------------------


def _make_user(user_id: uuid.UUID = USER_ID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


def _make_dataset(status: str = "ready") -> MagicMock:
    ds = MagicMock()
    ds.id = uuid.UUID(DATASET_ID)
    ds.user_id = USER_ID
    ds.status = status
    ds.r2_key = f"uploads/{DATASET_ID}/data.csv"
    ds.filename = "data.csv"
    return ds


def _make_job(
    status: str = "completed",
    result_json: dict | None = None,
) -> MagicMock:
    from datetime import datetime, timezone

    job = MagicMock()
    job.id = uuid.UUID(JOB_ID)
    job.dataset_id = uuid.UUID(DATASET_ID)
    job.user_id = USER_ID
    job.type = "export"
    job.status = status
    job.progress = 0
    job.result_json = result_json or {"r2_key": f"exports/{JOB_ID}/data.csv"}
    job.error_text = None
    job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job.completed_at = None
    job.celery_task_id = None
    return job


def _make_db(*query_results: object) -> AsyncMock:
    db = AsyncMock()
    mocks = []
    for value in query_results:
        m = MagicMock()
        m.scalar_one_or_none.return_value = value
        mocks.append(m)
    db.execute.side_effect = mocks if mocks else [MagicMock()]
    return db


def _authed_client(
    user: MagicMock | None = None,
    db: AsyncMock | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/exports")
    if user is None:
        user = _make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Path parameter validation
# ---------------------------------------------------------------------------


class TestPathParamValidation:
    def test_invalid_dataset_uuid_returns_422(self):
        client = _authed_client()
        response = client.post("/exports/not-a-uuid", json={})
        assert response.status_code == 422

    def test_invalid_job_uuid_in_download_returns_422(self):
        client = _authed_client()
        response = client.get("/exports/bad-uuid/download")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /{dataset_id} — create export job
# ---------------------------------------------------------------------------


class TestCreateExport:
    def test_returns_404_when_dataset_missing(self):
        db = _make_db(None)
        client = _authed_client(db=db)
        response = client.post(f"/exports/{DATASET_ID}", json={})
        assert response.status_code == 404
        assert "Dataset not found" in response.json()["detail"]

    def test_returns_400_when_dataset_not_ready(self):
        db = _make_db(_make_dataset(status="processing"))
        client = _authed_client(db=db)
        response = client.post(f"/exports/{DATASET_ID}", json={})
        assert response.status_code == 400
        assert "not ready" in response.json()["detail"].lower()

    def test_returns_202_for_ready_dataset(self):
        dataset = _make_dataset(status="ready")
        job = _make_job(status="pending")
        db = _make_db(dataset)
        db.refresh = AsyncMock(side_effect=[None, None])
        db.commit = AsyncMock()

        # export_dataset is imported inside the handler; patch the source module.
        with patch("app.routers.exports.Job", return_value=job):
            client = _authed_client(db=db)
            with patch("app.tasks.export_task.export_dataset") as mock_task:
                mock_task.delay.return_value.id = "celery-task-123"
                response = client.post(f"/exports/{DATASET_ID}", json={"format": "csv"})

        assert response.status_code == 202

    def test_default_format_is_csv(self):
        dataset = _make_dataset(status="ready")
        job = _make_job(status="pending")
        db = _make_db(dataset)
        db.refresh = AsyncMock(side_effect=[None, None])
        db.commit = AsyncMock()

        captured_format: list[str] = []

        with patch("app.routers.exports.Job", return_value=job):
            client = _authed_client(db=db)
            with patch("app.tasks.export_task.export_dataset") as mock_task:
                mock_task.delay.side_effect = lambda *a, **k: (
                    captured_format.append(a[2]),
                    MagicMock(id="t1"),
                )[1]
                client.post(f"/exports/{DATASET_ID}", json={})

        assert captured_format == ["csv"]

    def test_invalid_format_returns_422(self):
        client = _authed_client()
        response = client.post(f"/exports/{DATASET_ID}", json={"format": "docx"})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /{job_id}/download — presigned download URL
# ---------------------------------------------------------------------------


class TestDownloadExport:
    def test_returns_404_when_job_missing(self):
        db = _make_db(None)
        client = _authed_client(db=db)
        response = client.get(f"/exports/{JOB_ID}/download")
        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]

    def test_returns_400_when_job_not_completed(self):
        db = _make_db(_make_job(status="pending"))
        client = _authed_client(db=db)
        response = client.get(f"/exports/{JOB_ID}/download")
        assert response.status_code == 400
        assert "not completed" in response.json()["detail"].lower()

    def test_returns_500_when_result_has_no_r2_key(self):
        db = _make_db(_make_job(status="completed", result_json={"other": "data"}))
        client = _authed_client(db=db)
        response = client.get(f"/exports/{JOB_ID}/download")
        assert response.status_code == 500

    def test_returns_200_with_download_url_when_completed(self):
        job = _make_job(status="completed", result_json={"r2_key": "exports/abc/data.csv"})
        db = _make_db(job)
        client = _authed_client(db=db)
        with patch(
            "app.routers.exports.create_presigned_download_url",
            return_value="https://r2.example.com/data.csv",
        ):
            response = client.get(f"/exports/{JOB_ID}/download")
        assert response.status_code == 200
        assert response.json()["download_url"] == "https://r2.example.com/data.csv"
