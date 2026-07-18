"""Tests for Sentry initialization in app.main.

Sentry is a no-op when SENTRY_DSN is empty (the dev default) and initialises
with FastApiIntegration when a DSN is configured. These tests mock sentry_sdk.init
so nothing actually connects to Sentry.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.main import _init_sentry


class TestSentryInit:
    def test_no_op_when_dsn_is_empty(self) -> None:
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main.sentry_sdk.init") as mock_init,
        ):
            mock_settings.SENTRY_DSN = ""
            _init_sentry()
            mock_init.assert_not_called()

    def test_initialises_when_dsn_is_set(self) -> None:
        dsn = "https://abc123@o0.ingest.sentry.io/0"
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main.sentry_sdk.init") as mock_init,
        ):
            mock_settings.SENTRY_DSN = dsn
            mock_settings.ENVIRONMENT = "production"
            _init_sentry()
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs["dsn"] == dsn
            assert call_kwargs["environment"] == "production"
            assert call_kwargs["send_default_pii"] is False

    def test_fastapi_integration_is_included(self) -> None:
        dsn = "https://abc123@o0.ingest.sentry.io/0"
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main.sentry_sdk.init") as mock_init,
        ):
            mock_settings.SENTRY_DSN = dsn
            mock_settings.ENVIRONMENT = "staging"
            _init_sentry()
            integrations = mock_init.call_args.kwargs.get("integrations", [])
            from sentry_sdk.integrations.fastapi import FastApiIntegration

            assert any(isinstance(i, FastApiIntegration) for i in integrations)

    @pytest.mark.parametrize("env", ["development", "staging", "production"])
    def test_environment_is_forwarded(self, env: str) -> None:
        dsn = "https://abc123@o0.ingest.sentry.io/0"
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main.sentry_sdk.init") as mock_init,
        ):
            mock_settings.SENTRY_DSN = dsn
            mock_settings.ENVIRONMENT = env
            _init_sentry()
            assert mock_init.call_args.kwargs["environment"] == env
