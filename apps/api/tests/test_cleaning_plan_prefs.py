"""create_cleaning_plan threads the user's preferences into planning."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.cleaning import create_cleaning_plan


@pytest.mark.asyncio
async def test_create_plan_threads_domain_sample_size_and_instructions():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.preferences = {
        "domain": "generic",
        "ai_sample_size": 42,
        "custom_instructions": "drop column X",
    }

    dataset = MagicMock()
    dataset.id = uuid.uuid4()
    dataset.status = "ready"
    dataset.profile_json = {"columns": {"a": {}}}
    dataset.r2_key = "key"
    dataset.filename = "data.csv"

    db = AsyncMock()
    db.add = MagicMock()

    captured: dict = {}

    def fake_read_all_rows(fb, fname, max_rows=500):
        captured["max_rows"] = max_rows
        return [{"a": 1}]

    def fake_detect(df, domain=None):
        captured["domain"] = domain
        return {}

    def fake_generate(profile_json, sample_rows, dataset_id=None, user_instructions=None):
        captured["user_instructions"] = user_instructions
        return [{"operation": "strip_whitespace", "column": "a", "params": {}, "description": "s"}]

    with (
        patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch(
            "app.routers.cleaning._get_dataset_or_404", new_callable=AsyncMock, return_value=dataset
        ),
        patch("app.routers.cleaning.download_file_bytes", return_value=b"a\n1\n"),
        patch("app.routers.cleaning._read_all_rows", side_effect=fake_read_all_rows),
        patch("app.routers.cleaning.read_dataframe", return_value=MagicMock()),
        patch("app.tasks.profile_task.detect_quality_issues", side_effect=fake_detect),
        patch("app.services.cleaning.generate_cleaning_plan", side_effect=fake_generate),
        patch("app.routers.cleaning.JobResponse") as mock_jr,
    ):
        mock_jr.model_validate.return_value = "job-response"
        result = await create_cleaning_plan(dataset.id, user, db, None)

    assert captured["max_rows"] == 42  # ai_sample_size
    assert captured["domain"] == "generic"  # domain preference (not auto)
    assert "drop column X" in captured["user_instructions"]  # standing custom instructions
    assert result == "job-response"


@pytest.mark.asyncio
async def test_auto_domain_becomes_none_for_autodetection():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.preferences = {}  # domain defaults to "auto"

    dataset = MagicMock()
    dataset.id = uuid.uuid4()
    dataset.status = "ready"
    dataset.profile_json = {"columns": {"a": {}}}
    dataset.r2_key = "key"
    dataset.filename = "data.csv"

    db = AsyncMock()
    db.add = MagicMock()
    captured: dict = {}

    with (
        patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch(
            "app.routers.cleaning._get_dataset_or_404", new_callable=AsyncMock, return_value=dataset
        ),
        patch("app.routers.cleaning.download_file_bytes", return_value=b"a\n1\n"),
        patch("app.routers.cleaning._read_all_rows", return_value=[{"a": 1}]),
        patch("app.routers.cleaning.read_dataframe", return_value=MagicMock()),
        patch(
            "app.tasks.profile_task.detect_quality_issues",
            side_effect=lambda df, domain=None: captured.update(domain=domain) or {},
        ),
        patch("app.services.cleaning.generate_cleaning_plan", return_value=[]),
        patch("app.routers.cleaning.JobResponse") as mock_jr,
    ):
        mock_jr.model_validate.return_value = "ok"
        await create_cleaning_plan(dataset.id, user, db, None)

    assert captured["domain"] is None  # "auto" → None → auto-detection
