"""User-facing error messages for failed jobs.

``jobs.error_text`` is rendered verbatim in the frontend's error card.
Infrastructure failures (database errors carry raw SQL in their message)
must not leak internals to the UI — the full exception is always available
in the worker logs via ``logger.exception``.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

_GENERIC_MESSAGE = (
    "Something unexpected went wrong while processing this job. "
    "The details have been logged — please try again."
)
_MAX_LENGTH = 300


def user_facing_error(exc: BaseException) -> str:
    """Return a message safe to show in the UI for a failed job."""
    if isinstance(exc, SQLAlchemyError):
        return _GENERIC_MESSAGE
    message = str(exc).strip()
    if not message:
        return f"{type(exc).__name__} (no details available)"
    return message[:_MAX_LENGTH]
