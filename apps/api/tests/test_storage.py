"""Unit tests for storage helper functions (pure/offline)."""

from __future__ import annotations

import re
import uuid

from app.services.storage import generate_upload_key


class TestGenerateUploadKey:
    def _parse_key(self, key: str):
        """Split 'uploads/<user_id>/<ts>_<uid>_<name>' into parts."""
        parts = key.split("/")
        assert parts[0] == "uploads"
        return parts[1], parts[2]  # user_id_segment, filename_segment

    def test_format_prefix(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "data.csv")
        assert key.startswith(f"uploads/{uid}/")

    def test_ends_with_sanitized_filename(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "my_data.csv")
        assert key.endswith("my_data.csv")

    def test_path_traversal_stripped(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "../../etc/passwd")
        # Only the basename should remain, no directory components
        assert ".." not in key
        assert "etc" not in key
        assert key.endswith("passwd")

    def test_path_traversal_with_filename(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "../secret/data.csv")
        assert ".." not in key
        assert "secret" not in key
        assert key.endswith("data.csv")

    def test_special_chars_sanitized(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "my file (1).csv")
        # Spaces and parens should be replaced with underscores
        assert " " not in key
        assert "(" not in key
        assert ")" not in key

    def test_allowed_chars_preserved(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "my-data_v2.csv")
        assert key.endswith("my-data_v2.csv")

    def test_unique_per_call(self):
        uid = uuid.uuid4()
        key1 = generate_upload_key(uid, "file.csv")
        key2 = generate_upload_key(uid, "file.csv")
        assert key1 != key2

    def test_user_id_embedded(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "data.csv")
        assert str(uid) in key

    def test_timestamp_present(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "data.csv")
        filename_segment = key.split("/")[2]
        # Timestamp is the first part before the first underscore-separated token
        ts_part = filename_segment.split("_")[0]
        assert re.fullmatch(r"\d{14}", ts_part), f"Expected 14-digit timestamp, got {ts_part!r}"

    def test_returns_string(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "test.csv")
        assert isinstance(key, str)

    def test_dot_only_extension(self):
        uid = uuid.uuid4()
        key = generate_upload_key(uid, "data.parquet")
        assert key.endswith("data.parquet")
