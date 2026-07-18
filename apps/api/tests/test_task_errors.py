"""Tests for user-facing job error messages.

``jobs.error_text`` is rendered verbatim in the frontend's error card, so
infrastructure errors (raw SQL statements, driver noise) must be replaced
with a readable message; the full exception always goes to the logs.
"""

from __future__ import annotations

from sqlalchemy.exc import OperationalError, StatementError

from app.tasks._errors import user_facing_error


class TestUserFacingError:
    def test_plain_app_errors_pass_through(self):
        assert user_facing_error(ValueError("Column 'region' not found")) == (
            "Column 'region' not found"
        )

    def test_sqlalchemy_errors_are_replaced_with_generic_message(self):
        exc = StatementError(
            "(builtins.TypeError) Object of type Timestamp is not JSON serializable",
            "UPDATE jobs SET result_json=%(result_json)s::JSONB",
            {},
            TypeError("Object of type Timestamp is not JSON serializable"),
        )
        msg = user_facing_error(exc)
        assert "UPDATE" not in msg
        assert "JSONB" not in msg
        assert "unexpected" in msg.lower() or "internal" in msg.lower()

    def test_operational_errors_are_replaced_with_generic_message(self):
        exc = OperationalError("SELECT 1", {}, Exception("connection refused"))
        msg = user_facing_error(exc)
        assert "SELECT" not in msg

    def test_long_messages_are_truncated(self):
        msg = user_facing_error(ValueError("x" * 1000))
        assert len(msg) <= 300

    def test_empty_message_falls_back_to_class_name(self):
        assert "ValueError" in user_facing_error(ValueError())
