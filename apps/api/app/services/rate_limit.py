"""Redis-based sliding window rate limiter for expensive operations.

Designed to protect Claude API calls and other costly endpoints from abuse.
Uses a singleton Redis connection pool to avoid per-request overhead.
"""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton Redis connection pool — reused across all rate limit checks.
# Closed via shutdown hook in main.py lifespan.
_redis_pool: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.REDIS_URL)
    return _redis_pool


async def close_redis_pool() -> None:
    """Close the rate limiter's Redis pool. Call from app lifespan shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


async def check_rate_limit(
    user_id: str,
    action: str = "claude_api",
    max_calls: int = 20,
    window_seconds: int = 3600,
) -> None:
    """Check and increment a per-user rate limit counter.

    Uses a Redis sorted set with timestamp-based sliding window.
    Only adds the request to the set if the limit has not been exceeded,
    so rejected requests are not counted.

    Raises:
        HTTPException(429) if rate limit exceeded.
    """
    r = _get_redis()
    key = f"rate_limit:{action}:{user_id}"
    now = time.time()
    window_start = now - window_seconds

    pipe = r.pipeline()
    # Remove entries outside the window
    pipe.zremrangebyscore(key, 0, window_start)
    # Count entries in the window (before adding current request)
    pipe.zcard(key)
    results = await pipe.execute()

    current_count: int = results[1]

    if current_count >= max_calls:
        logger.warning(
            "Rate limit exceeded for user %s on action %s: %d/%d in %ds",
            user_id, action, current_count, max_calls, window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {max_calls} {action} calls per {window_seconds // 60} minutes",
        )

    # Only add the entry after confirming the limit is not exceeded
    pipe2 = r.pipeline()
    pipe2.zadd(key, {str(now): now})
    pipe2.expire(key, window_seconds + 60)
    await pipe2.execute()
