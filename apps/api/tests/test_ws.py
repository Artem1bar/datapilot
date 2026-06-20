"""Unit tests for the WebSocket /ws/jobs/{job_id} router."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from app.routers.ws import _authenticate_ws, job_progress_ws

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

JOB_ID = uuid.uuid4()


def _make_websocket(token: str | None = "valid-token") -> MagicMock:
    ws = MagicMock()
    ws.query_params = MagicMock()
    ws.query_params.get = MagicMock(return_value=token)
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    return ws


def _make_job(job_id: uuid.UUID = JOB_ID) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    return job


def _db_factory(query_result: object = None):
    """Return a session-factory-like callable that yields a mock session."""
    @asynccontextmanager
    async def _ctx():
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = query_result
        session.execute = AsyncMock(return_value=result)
        yield session
    return _ctx


def _failing_db_factory(exc: Exception | None = None):
    """Return a session-factory-like callable that raises on entry."""
    err = exc or RuntimeError("DB is down")

    @asynccontextmanager
    async def _ctx():
        raise err
        yield  # noqa: unreachable  — makes this a generator function

    return _ctx


async def _progress_gen(*updates):
    """Yield a sequence of progress update dicts."""
    for update in updates:
        yield update


# ---------------------------------------------------------------------------
# _authenticate_ws — token checks
# ---------------------------------------------------------------------------


class TestAuthenticateWs:
    @pytest.mark.asyncio
    async def test_missing_token_returns_false(self) -> None:
        ws = _make_websocket(token=None)
        result = await _authenticate_ws(ws, JOB_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_token_sends_error_message(self) -> None:
        ws = _make_websocket(token=None)
        await _authenticate_ws(ws, JOB_ID)
        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert "error" in payload

    @pytest.mark.asyncio
    async def test_missing_token_closes_with_4001(self) -> None:
        ws = _make_websocket(token=None)
        await _authenticate_ws(ws, JOB_ID)
        ws.close.assert_awaited_once()
        assert ws.close.call_args[1]["code"] == 4001

    # ---------------------------------------------------------------------------
    # Job-not-found cases — patch at the source module, not ws module
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_job_not_found_returns_false(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _db_factory(None)):
            result = await _authenticate_ws(ws, JOB_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_job_not_found_closes_with_4004(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _db_factory(None)):
            await _authenticate_ws(ws, JOB_ID)
        ws.close.assert_awaited_once()
        assert ws.close.call_args[1]["code"] == 4004

    @pytest.mark.asyncio
    async def test_job_not_found_sends_error_message(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _db_factory(None)):
            await _authenticate_ws(ws, JOB_ID)
        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert "error" in payload

    # ---------------------------------------------------------------------------
    # DB error case
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_db_error_returns_false(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _failing_db_factory()):
            result = await _authenticate_ws(ws, JOB_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_db_error_closes_with_4000(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _failing_db_factory()):
            await _authenticate_ws(ws, JOB_ID)
        ws.close.assert_awaited_once()
        assert ws.close.call_args[1]["code"] == 4000

    # ---------------------------------------------------------------------------
    # Happy path
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_valid_token_and_job_returns_true(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _db_factory(_make_job())):
            result = await _authenticate_ws(ws, JOB_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_valid_auth_does_not_close_connection(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _db_factory(_make_job())):
            await _authenticate_ws(ws, JOB_ID)
        ws.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_auth_does_not_send_error(self) -> None:
        ws = _make_websocket()
        with patch("app.db.engine.async_session", _db_factory(_make_job())):
            await _authenticate_ws(ws, JOB_ID)
        ws.send_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# job_progress_ws — full handler
# ---------------------------------------------------------------------------


class TestJobProgressWs:
    @pytest.mark.asyncio
    async def test_auth_failure_exits_without_streaming(self) -> None:
        ws = _make_websocket(token=None)
        await job_progress_ws(ws, JOB_ID)
        # send_text called once for the auth error, streaming never runs
        assert ws.send_text.await_count == 1

    @pytest.mark.asyncio
    async def test_progress_updates_are_sent_to_client(self) -> None:
        ws = _make_websocket()
        updates = [
            {"job_id": str(JOB_ID), "status": "running", "progress": 50, "message": "halfway"},
            {"job_id": str(JOB_ID), "status": "completed", "progress": 100, "message": "done"},
        ]

        with (
            patch("app.db.engine.async_session", _db_factory(_make_job())),
            patch(
                "app.routers.ws.subscribe_progress",
                return_value=_progress_gen(*updates),
            ),
        ):
            await job_progress_ws(ws, JOB_ID)

        assert ws.send_text.await_count == 2
        sent = [json.loads(c[0][0]) for c in ws.send_text.await_args_list]
        assert sent[0]["status"] == "running"
        assert sent[1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_websocket_disconnect_is_handled_gracefully(self) -> None:
        ws = _make_websocket()

        async def _disconnecting_gen():
            raise WebSocketDisconnect(code=1001)
            yield  # noqa: unreachable

        with (
            patch("app.db.engine.async_session", _db_factory(_make_job())),
            patch("app.routers.ws.subscribe_progress", return_value=_disconnecting_gen()),
        ):
            await job_progress_ws(ws, JOB_ID)

        # Should not raise; close() is skipped when client already disconnected
        ws.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_accepted_before_auth(self) -> None:
        ws = _make_websocket(token=None)
        await job_progress_ws(ws, JOB_ID)
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_closed_after_stream_ends(self) -> None:
        ws = _make_websocket()
        updates = [
            {"job_id": str(JOB_ID), "status": "completed", "progress": 100, "message": ""},
        ]

        with (
            patch("app.db.engine.async_session", _db_factory(_make_job())),
            patch(
                "app.routers.ws.subscribe_progress",
                return_value=_progress_gen(*updates),
            ),
        ):
            await job_progress_ws(ws, JOB_ID)

        ws.close.assert_awaited_once()
