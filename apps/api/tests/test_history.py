"""Unit tests for app/services/history.py (offline, no I/O)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone

import pytest

from app.services.history import create_history_entry


class TestCreateHistoryEntry:
    def test_required_fields_present(self):
        entry = create_history_entry(
            dataset_id="ds-1",
            operation_type="drop_nulls",
            description="Drop null rows in column age",
            snapshot_key="snapshots/ds-1/snap-001",
        )
        assert "id" in entry
        assert "dataset_id" in entry
        assert "operation_type" in entry
        assert "description" in entry
        assert "snapshot_key" in entry
        assert "metadata" in entry
        assert "created_at" in entry

    def test_values_match_inputs(self):
        entry = create_history_entry(
            dataset_id="ds-abc",
            operation_type="rename_column",
            description="Rename col_a to age",
            snapshot_key="snapshots/snap-2",
        )
        assert entry["dataset_id"] == "ds-abc"
        assert entry["operation_type"] == "rename_column"
        assert entry["description"] == "Rename col_a to age"
        assert entry["snapshot_key"] == "snapshots/snap-2"

    def test_id_is_valid_uuid(self):
        entry = create_history_entry(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
        )
        parsed = uuid.UUID(entry["id"])
        assert str(parsed) == entry["id"]

    def test_each_call_produces_unique_id(self):
        kwargs = dict(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
        )
        ids = {create_history_entry(**kwargs)["id"] for _ in range(10)}
        assert len(ids) == 10

    def test_metadata_none_defaults_to_empty_dict(self):
        entry = create_history_entry(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
            metadata=None,
        )
        assert entry["metadata"] == {}

    def test_metadata_omitted_defaults_to_empty_dict(self):
        entry = create_history_entry(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
        )
        assert entry["metadata"] == {}

    def test_metadata_preserved_when_provided(self):
        meta = {"rows_dropped": 3, "column": "age"}
        entry = create_history_entry(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
            metadata=meta,
        )
        assert entry["metadata"] == meta

    def test_created_at_is_iso8601_utc(self):
        before = datetime.now(UTC)
        entry = create_history_entry(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
        )
        after = datetime.now(UTC)
        ts = datetime.fromisoformat(entry["created_at"])
        assert ts.tzinfo is not None
        assert before <= ts <= after

    def test_metadata_mutation_does_not_affect_original(self):
        meta = {"a": 1}
        entry = create_history_entry(
            dataset_id="d",
            operation_type="op",
            description="desc",
            snapshot_key="key",
            metadata=meta,
        )
        entry["metadata"]["b"] = 2
        assert "b" not in meta

    def test_empty_string_fields_accepted(self):
        entry = create_history_entry(
            dataset_id="",
            operation_type="",
            description="",
            snapshot_key="",
        )
        assert entry["dataset_id"] == ""
        assert entry["operation_type"] == ""
        assert entry["description"] == ""
        assert entry["snapshot_key"] == ""
