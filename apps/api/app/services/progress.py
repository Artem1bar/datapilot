"""Redis pub/sub helpers for broadcasting job progress updates."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a shared async Redis connection."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_pool


def _channel_name(job_id: uuid.UUID) -> str:
    return f"job:{job_id}:progress"


async def publish_progress(
    job_id: uuid.UUID,
    status: str,
    progress: int,
    message: str = "",
    result: dict[str, Any] | None = None,
) -> None:
    """Publish a progress update for a job."""
    r = await get_redis()
    payload = json.dumps({
        "job_id": str(job_id),
        "status": status,
        "progress": progress,
        "message": message,
        "result": result,
    })
    await r.publish(_channel_name(job_id), payload)


async def subscribe_progress(job_id: uuid.UUID) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator that yields progress updates for a job."""
    r = await get_redis()
    pubsub = r.pubsub()
    channel = _channel_name(job_id)
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                yield data
                if data.get("status") in ("completed", "failed"):
                    break
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def close_redis() -> None:
    """Close the shared Redis pool."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
