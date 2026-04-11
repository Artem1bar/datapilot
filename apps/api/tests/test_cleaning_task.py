"""Tests for the cleaning_task Celery task."""

from __future__ import annotations

import io
import json
import uuid
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATASET_ID = str(uuid.uuid4())
JOB_ID = str(uuid.uuid4())

SIMPLE_CSV = "id,name,score\n1,Alice,100\n2,Bob,85\n3,Carol,90\n"
SIMPLE_STEPS = [
    {"operation": "strip_whitespace", "column": "name", "description": "Strip whitespace from name"},
]


def _make_mock_dataset(
    r2_key: str = "uploads/test.csv",
    filename: str = "test.csv",
    profile_json: dict | None = None,
):
    """Return a mock Dataset ORM object."""
    ds = MagicMock()
    ds.r2_key = r2_key
    ds.filename = filename
    ds.profile_json = profile_json or {"data_quality": {"name": {"flag": "whitespace"}}}
    return ds


def _make_verification_report(
    overall_passed: bool = True,
    audit_completeness: float = 0.95,
):
    """Return a mock VerificationReport."""
    report = MagicMock()
    report.overall_passed = overall_passed
    report.audit_completeness = audit_completeness
    report.to_dict.return_value = {
        "overall_passed": overall_passed,
        "audit_completeness": audit_completeness,
        "flags_before": {},
        "flags_after": {},
        "flags_resolved": [],
        "flags_remaining": [],
        "flags_new": [],
        "step_results": [],
        "failed_steps": [],
        "summary": "OK" if overall_passed else "Issues found",
    }
    return report


def _make_agent_result(passed: bool = True, remediation_steps: list | None = None):
    """Return a mock AgentVerificationResult."""
    result = MagicMock()
    result.passed = passed
    result.confidence = 0.9 if passed else 0.5
    result.issues_found = (
        ()
        if passed
        else ({"column": "score", "issue": "outlier", "severity": "HIGH", "detail": "test"},)
    )
    result.recommendations = ()
    result.remediation_steps = tuple(remediation_steps or [])
    result.to_dict.return_value = {
        "passed": result.passed,
        "confidence": result.confidence,
        "issues_found": list(result.issues_found),
        "recommendations": list(result.recommendations),
        "remediation_steps": list(result.remediation_steps),
        "summary": "Agent OK" if passed else "Agent found issues",
    }
    return result


def _setup_session_mock(mock_session_cls, dataset: MagicMock):
    """Configure the Session context manager mock to return dataset on select queries."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = dataset
    mock_session.execute.return_value = mock_result

    return mock_session


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_P_ENGINE = "app.tasks.cleaning_task._get_sync_engine"
_P_DOWNLOAD = "app.tasks.cleaning_task.download_file_bytes"
_P_S3 = "app.tasks.cleaning_task.get_s3_client"
_P_PROGRESS = "app.tasks.cleaning_task._publish_progress_sync"
_P_VALIDATE = "app.utils.file_validation.validate_file_content"
_P_EXEC_PLAN = "app.services.cleaning.execute_cleaning_plan"
_P_VERIFY = "app.services.verification.verify_cleaning_result"
_P_AGENT = "app.services.verification_agent.run_verification_agent"


def _call_task(dataset_id: str, job_id: str, steps_json: str):
    """Call the clean_dataset task, bypassing Celery."""
    from app.tasks.cleaning_task import clean_dataset
    return clean_dataset.__wrapped__(dataset_id, job_id, steps_json)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCleanDatasetTask:

    @patch(_P_S3)
    @patch(_P_DOWNLOAD)
    @patch(_P_VALIDATE, return_value=True)
    @patch(_P_PROGRESS)
    @patch(_P_VERIFY)
    @patch(_P_EXEC_PLAN)
    @patch(_P_ENGINE)
    def test_cleaning_task_full_flow_success(
        self,
        mock_engine,
        mock_execute_plan,
        mock_verify,
        mock_progress,
        mock_validate,
        mock_download,
        mock_s3,
    ):
        mock_engine.return_value = MagicMock()
        mock_download.return_value = SIMPLE_CSV.encode()

        cleaned_df = pd.read_csv(io.BytesIO(SIMPLE_CSV.encode()))
        cleaned_df["name"] = cleaned_df["name"].str.strip()
        audit_log = [
            {
                "row": 1,
                "column": "name",
                "original_value": " Alice",
                "new_value": "Alice",
                "operation": "strip_whitespace",
                "rule": "strip",
            }
        ]
        mock_execute_plan.return_value = (cleaned_df, audit_log, [])

        mock_verify.return_value = _make_verification_report(
            overall_passed=True, audit_completeness=0.95
        )

        mock_s3.return_value = MagicMock()
        dataset = _make_mock_dataset()

        with patch("sqlalchemy.orm.Session") as mock_session_cls:
            _setup_session_mock(mock_session_cls, dataset)
            result = _call_task(DATASET_ID, JOB_ID, json.dumps(SIMPLE_STEPS))

        assert result["status"] == "completed"
        assert result["dataset_id"] == DATASET_ID
        assert result["job_id"] == JOB_ID

        mock_execute_plan.assert_called_once()
        call_args = mock_execute_plan.call_args
        assert call_args[0][1] == SIMPLE_STEPS

        mock_s3.return_value.put_object.assert_called_once()

    @patch(_P_S3)
    @patch(_P_DOWNLOAD)
    @patch(_P_VALIDATE, return_value=True)
    @patch(_P_PROGRESS)
    @patch(_P_VERIFY)
    @patch(_P_EXEC_PLAN)
    @patch(_P_ENGINE)
    @patch(_P_AGENT)
    def test_cleaning_task_with_failed_steps(
        self,
        mock_agent,
        mock_engine,
        mock_execute_plan,
        mock_verify,
        mock_progress,
        mock_validate,
        mock_download,
        mock_s3,
    ):
        mock_engine.return_value = MagicMock()
        mock_download.return_value = SIMPLE_CSV.encode()

        cleaned_df = pd.read_csv(io.BytesIO(SIMPLE_CSV.encode()))
        failed_steps = [
            {"operation": "cast_type", "column": "name", "error": "Cannot cast string to float"}
        ]
        mock_execute_plan.return_value = (cleaned_df, [], failed_steps)

        mock_verify.return_value = _make_verification_report(
            overall_passed=False, audit_completeness=0.5
        )

        mock_agent.return_value = _make_agent_result(passed=True)
        mock_s3.return_value = MagicMock()
        dataset = _make_mock_dataset()

        with patch("sqlalchemy.orm.Session") as mock_session_cls:
            mock_session = _setup_session_mock(mock_session_cls, dataset)
            result = _call_task(DATASET_ID, JOB_ID, json.dumps(SIMPLE_STEPS))

        assert result["status"] == "completed"
        mock_agent.assert_called_once()
        mock_session.commit.assert_called()

    @patch(_P_S3)
    @patch(_P_DOWNLOAD)
    @patch(_P_VALIDATE, return_value=True)
    @patch(_P_PROGRESS)
    @patch(_P_VERIFY)
    @patch(_P_EXEC_PLAN)
    @patch(_P_ENGINE)
    @patch(_P_AGENT)
    def test_cleaning_task_triggers_verification_agent_on_failure(
        self,
        mock_agent,
        mock_engine,
        mock_execute_plan,
        mock_verify,
        mock_progress,
        mock_validate,
        mock_download,
        mock_s3,
    ):
        mock_engine.return_value = MagicMock()
        mock_download.return_value = SIMPLE_CSV.encode()

        cleaned_df = pd.read_csv(io.BytesIO(SIMPLE_CSV.encode()))
        mock_execute_plan.return_value = (cleaned_df, [], [])

        mock_verify.return_value = _make_verification_report(
            overall_passed=False, audit_completeness=0.7
        )

        mock_agent.return_value = _make_agent_result(passed=False, remediation_steps=[])
        mock_s3.return_value = MagicMock()
        dataset = _make_mock_dataset()

        with patch("sqlalchemy.orm.Session") as mock_session_cls:
            _setup_session_mock(mock_session_cls, dataset)
            result = _call_task(DATASET_ID, JOB_ID, json.dumps(SIMPLE_STEPS))

        assert result["status"] == "completed"
        mock_agent.assert_called_once()
        agent_call_kwargs = mock_agent.call_args.kwargs
        assert "original_quality_flags" in agent_call_kwargs
        assert "deterministic_report" in agent_call_kwargs

    @patch(_P_PROGRESS)
    @patch(_P_DOWNLOAD)
    @patch(_P_VALIDATE, return_value=False)
    @patch(_P_ENGINE)
    def test_cleaning_task_file_validation_rejects_bad_file(
        self,
        mock_engine,
        mock_validate,
        mock_download,
        mock_progress,
    ):
        mock_engine.return_value = MagicMock()
        mock_download.return_value = b"PK\x03\x04not-really-csv"
        dataset = _make_mock_dataset(filename="data.csv")

        from app.tasks.cleaning_task import clean_dataset

        with (
            patch("sqlalchemy.orm.Session") as mock_session_cls,
            patch.object(clean_dataset, "retry", side_effect=Exception("retry-called")) as mock_retry,
        ):
            _setup_session_mock(mock_session_cls, dataset)

            with pytest.raises(Exception, match="retry-called"):
                _call_task(DATASET_ID, JOB_ID, json.dumps(SIMPLE_STEPS))

        mock_retry.assert_called_once()
