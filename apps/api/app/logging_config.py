"""Structured logging: JSON logs in production, readable logs in dev.

A request-id context variable is injected into every log record so a request's
logs can be correlated (the RequestContextMiddleware sets it per request).
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Standard LogRecord attributes — anything else on a record is a caller "extra".
_STD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}


class JsonLogFormatter(logging.Formatter):
    """Render log records as single-line JSON, including request_id and extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, json_logs: bool, level: int = logging.INFO) -> None:
    """Install a single handler on the root logger (JSON or readable)."""
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-5s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
