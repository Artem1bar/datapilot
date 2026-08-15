"""Unit tests for rate_limit.check_rate_limit's Redis sliding-window logic.

Previous tests always mocked check_rate_limit itself; these exercise
the actual pipeline calls so a regression in the Redis interaction
would be caught here rather than silently passing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import rate_limit


def _make_redis_pipe(zcard_result: int) -> MagicMock:
    """Return a mocked async pipeline that reports `zcard_result` entries."""
    pipe = AsyncMock()
    pipe.zremrangebyscore = MagicMock()
    pipe.zcard = MagicMock()
    pipe.zadd = MagicMock()
    pipe.expire = MagicMock()
    # First pipeline execute returns [None, count]; second returns [None, None]
    pipe.execute = AsyncMock(side_effect=[[None, zcard_result], [None, None]])
    return pipe


def _make_redis(zcard_result: int) -> MagicMock:
    r = MagicMock()
    r.pipeline.return_value = _make_redis_pipe(zcard_result)
    return r


# ---------------------------------------------------------------------------
# Under the limit: passes and records the call
# ---------------------------------------------------------------------------


class TestCheckRateLimitUnderLimit:
    @pytest.mark.asyncio
    async def test_passes_when_count_below_limit(self) -> None:
        r = _make_redis(zcard_result=5)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            # Should not raise
            await rate_limit.check_rate_limit("user-1", max_calls=20, window_seconds=3600)

    @pytest.mark.asyncio
    async def test_calls_zremrangebyscore_to_prune_old_entries(self) -> None:
        r = _make_redis(zcard_result=0)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            await rate_limit.check_rate_limit("user-1", action="test_action")
        pipe = r.pipeline.return_value
        pipe.zremrangebyscore.assert_called_once()
        # First arg is the key, second is 0 (min), third is window_start
        args = pipe.zremrangebyscore.call_args.args
        assert args[0] == "rate_limit:test_action:user-1"
        assert args[1] == 0

    @pytest.mark.asyncio
    async def test_records_request_via_zadd_after_limit_check(self) -> None:
        r = _make_redis(zcard_result=0)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            await rate_limit.check_rate_limit("user-1")
        pipe = r.pipeline.return_value
        # zadd and expire must be called (on the second pipeline usage)
        pipe.zadd.assert_called_once()
        pipe.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_correct_redis_key_format(self) -> None:
        r = _make_redis(zcard_result=0)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            await rate_limit.check_rate_limit("abc-user", action="my_action")
        pipe = r.pipeline.return_value
        expire_key = pipe.expire.call_args.args[0]
        assert expire_key == "rate_limit:my_action:abc-user"

    @pytest.mark.asyncio
    async def test_expire_ttl_slightly_exceeds_window(self) -> None:
        """TTL is window_seconds + 60 so keys outlive their window by a margin."""
        r = _make_redis(zcard_result=0)
        window = 3600
        with patch("app.services.rate_limit._get_redis", return_value=r):
            await rate_limit.check_rate_limit("u1", window_seconds=window)
        pipe = r.pipeline.return_value
        ttl = pipe.expire.call_args.args[1]
        assert ttl == window + 60

    @pytest.mark.asyncio
    async def test_accepted_at_count_one_below_limit(self) -> None:
        r = _make_redis(zcard_result=19)  # limit is 20, count is 19 → ok
        with patch("app.services.rate_limit._get_redis", return_value=r):
            await rate_limit.check_rate_limit("u1", max_calls=20)
        pipe = r.pipeline.return_value
        pipe.zadd.assert_called_once()


# ---------------------------------------------------------------------------
# At or over the limit: raises 429 and does NOT record the call
# ---------------------------------------------------------------------------


class TestCheckRateLimitAtLimit:
    @pytest.mark.asyncio
    async def test_raises_429_at_exact_limit(self) -> None:
        r = _make_redis(zcard_result=20)  # exactly at limit
        with patch("app.services.rate_limit._get_redis", return_value=r):
            with pytest.raises(HTTPException) as exc:
                await rate_limit.check_rate_limit("u1", max_calls=20)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_raises_429_when_over_limit(self) -> None:
        r = _make_redis(zcard_result=50)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            with pytest.raises(HTTPException) as exc:
                await rate_limit.check_rate_limit("u1", max_calls=20)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_does_not_record_rejected_request(self) -> None:
        """Rate-limited requests must NOT be counted — only increment on accept."""
        r = _make_redis(zcard_result=20)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            with pytest.raises(HTTPException):
                await rate_limit.check_rate_limit("u1", max_calls=20)
        pipe = r.pipeline.return_value
        pipe.zadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_detail_includes_limit_and_window(self) -> None:
        r = _make_redis(zcard_result=20)
        with patch("app.services.rate_limit._get_redis", return_value=r):
            with pytest.raises(HTTPException) as exc:
                await rate_limit.check_rate_limit(
                    "u1", action="claude_api", max_calls=20, window_seconds=3600
                )
        assert "20" in exc.value.detail
        assert "claude_api" in exc.value.detail
