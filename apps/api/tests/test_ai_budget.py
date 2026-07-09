"""AI cost controls: global kill-switch + per-user daily budget."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services import rate_limit


@pytest.mark.asyncio
async def test_kill_switch_returns_503(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "AI_ENABLED", False)
    with pytest.raises(HTTPException) as exc:
        await rate_limit.enforce_ai_budget("u1")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_enforces_shared_daily_budget(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "AI_ENABLED", True)
    monkeypatch.setattr(rate_limit.settings, "AI_DAILY_CALL_BUDGET", 200)
    with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock) as mock_crl:
        await rate_limit.enforce_ai_budget("u1")
    mock_crl.assert_awaited_once()
    kwargs = mock_crl.call_args.kwargs
    assert kwargs["action"] == "ai_daily"  # shared across all AI endpoints
    assert kwargs["max_calls"] == 200
    assert kwargs["window_seconds"] == 86_400
