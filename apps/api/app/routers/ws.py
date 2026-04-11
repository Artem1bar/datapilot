"""WebSocket endpoint for real-time job progress updates."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.services.progress import subscribe_progress

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


async def _authenticate_ws(websocket: WebSocket, job_id: uuid.UUID) -> bool:
    """Verify that the WebSocket client owns the requested job.

    Accepts a ``token`` query parameter. In dev mode (no Clerk configured),
    accepts any non-empty token. In production, this should validate a
    Clerk JWT and match the user_id to the job's owner.

    Must be called AFTER ``websocket.accept()`` so close codes reach the client.

    Returns True if authorized, False otherwise (sends error and closes).
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.send_text(json.dumps({"error": "Missing auth token"}))
        await websocket.close(code=4001, reason="Missing auth token")
        return False

    # Verify job exists and belongs to the requesting user.
    # In dev mode we accept any non-empty token and skip user matching.
    # In production, decode the JWT to extract user_id and add
    # Job.user_id == user_id to the query.
    from app.db.engine import async_session as async_session_factory
    from app.models.job import Job

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job is None:
                await websocket.send_text(json.dumps({"error": "Job not found"}))
                await websocket.close(code=4004, reason="Job not found")
                return False
            # TODO(production): decode token, extract user_id, verify job.user_id == user_id
    except Exception as exc:
        logger.error("WebSocket auth DB error: %s", exc)
        await websocket.send_text(json.dumps({"error": "Internal error"}))
        await websocket.close(code=4000, reason="Internal error")
        return False

    return True


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: uuid.UUID) -> None:
    """Stream job progress updates to the client via WebSocket.

    Requires a ``token`` query parameter for authentication.

    The client connects and receives JSON messages of the form::

        {"job_id": "...", "status": "running", "progress": 42, "message": "...", "result": null}

    The connection is closed when the job reaches ``completed`` or ``failed``.
    """
    await websocket.accept()

    if not await _authenticate_ws(websocket, job_id):
        return

    disconnected = False
    try:
        async for update in subscribe_progress(job_id):
            await websocket.send_text(json.dumps(update))
    except WebSocketDisconnect:
        disconnected = True
    finally:
        if not disconnected:
            await websocket.close()
