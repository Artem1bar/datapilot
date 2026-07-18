"""Tests for the shared effective-file selection (revert semantics)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.dataset_versions import pick_effective_r2_key


def _job(result_json: dict | None) -> MagicMock:
    job = MagicMock()
    job.result_json = result_json
    return job


class TestPickEffectiveR2Key:
    def test_no_clean_jobs_returns_original(self):
        assert pick_effective_r2_key("uploads/u/a.csv", []) == "uploads/u/a.csv"

    def test_latest_clean_job_wins(self):
        jobs = [
            _job({"cleaned_r2_key": "uploads/u/a_cleaned_new.csv"}),
            _job({"cleaned_r2_key": "uploads/u/a_cleaned_old.csv"}),
        ]
        assert pick_effective_r2_key("uploads/u/a.csv", jobs) == "uploads/u/a_cleaned_new.csv"

    def test_reverted_latest_falls_back_to_previous(self):
        jobs = [
            _job({"cleaned_r2_key": "uploads/u/a_cleaned_new.csv", "reverted": True}),
            _job({"cleaned_r2_key": "uploads/u/a_cleaned_old.csv"}),
        ]
        assert pick_effective_r2_key("uploads/u/a.csv", jobs) == "uploads/u/a_cleaned_old.csv"

    def test_all_reverted_returns_original(self):
        jobs = [
            _job({"cleaned_r2_key": "uploads/u/a_cleaned_new.csv", "reverted": True}),
            _job({"cleaned_r2_key": "uploads/u/a_cleaned_old.csv", "reverted": True}),
        ]
        assert pick_effective_r2_key("uploads/u/a.csv", jobs) == "uploads/u/a.csv"

    def test_jobs_without_cleaned_key_are_skipped(self):
        jobs = [_job(None), _job({"cleaned_rows": 5})]
        assert pick_effective_r2_key("uploads/u/a.csv", jobs) == "uploads/u/a.csv"
