"""Structured logging formatter + request-id middleware."""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import JsonLogFormatter, request_id_ctx
from app.middleware import RequestContextMiddleware


def test_json_formatter_includes_request_id_and_extras():
    token = request_id_ctx.set("rid-1")
    try:
        record = logging.LogRecord("test", logging.INFO, "f.py", 1, "hello", None, None)
        record.method = "GET"  # a caller "extra"
        out = json.loads(JsonLogFormatter().format(record))
    finally:
        request_id_ctx.reset(token)

    assert out["message"] == "hello"
    assert out["level"] == "INFO"
    assert out["request_id"] == "rid-1"
    assert out["method"] == "GET"


def test_json_formatter_omits_request_id_when_unset():
    out = json.loads(
        JsonLogFormatter().format(logging.LogRecord("t", logging.INFO, "f", 1, "hi", None, None))
    )
    assert "request_id" not in out


def _app() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_middleware_adds_request_id_header():
    resp = _app().get("/ping")
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id")  # present and non-empty


def test_middleware_echoes_incoming_request_id():
    resp = _app().get("/ping", headers={"X-Request-ID": "trace-abc"})
    assert resp.headers.get("x-request-id") == "trace-abc"
