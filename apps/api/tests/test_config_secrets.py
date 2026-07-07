"""Production refuses to boot with default/missing secrets."""

from __future__ import annotations

from app.config import Settings

_REAL = {
    "R2_ACCESS_KEY_ID": "real-access-key",
    "R2_SECRET_ACCESS_KEY": "real-secret-key",
    "DATABASE_URL": "postgresql+asyncpg://user:pw@db.example.com:5432/prod",
    "ANTHROPIC_API_KEY": "sk-ant-real",
    "CLERK_JWT_ISSUER": "https://real.clerk.accounts.dev",
    "CLERK_WEBHOOK_SECRET": "whsec_real",
    "DEV_AUTH_BYPASS": False,
}


def test_no_problems_outside_production_even_with_defaults():
    s = Settings(ENVIRONMENT="development", R2_ACCESS_KEY_ID="minioadmin")
    assert s.production_secret_problems() == []


def test_flags_default_secrets_in_production():
    s = Settings(
        ENVIRONMENT="production",
        R2_ACCESS_KEY_ID="minioadmin",
        R2_SECRET_ACCESS_KEY="minioadmin",
        DATABASE_URL="postgresql+asyncpg://datapilot:datapilot@localhost:5432/datapilot",
        ANTHROPIC_API_KEY="sk-ant-real",  # set, so only the defaults below are flagged
    )
    problems = s.production_secret_problems()
    assert any("R2_ACCESS_KEY_ID" in p for p in problems)
    assert any("R2_SECRET_ACCESS_KEY" in p for p in problems)
    assert any("DATABASE_URL" in p for p in problems)


def test_flags_missing_clerk_and_bypass_in_production():
    s = Settings(
        ENVIRONMENT="production",
        **{**_REAL, "CLERK_JWT_ISSUER": "", "CLERK_WEBHOOK_SECRET": "", "DEV_AUTH_BYPASS": True},
    )
    problems = s.production_secret_problems()
    assert any("CLERK_JWT_ISSUER" in p for p in problems)
    assert any("CLERK_WEBHOOK_SECRET" in p for p in problems)
    assert any("DEV_AUTH_BYPASS" in p for p in problems)


def test_no_problems_when_production_fully_configured():
    s = Settings(ENVIRONMENT="production", **_REAL)
    assert s.production_secret_problems() == []


def test_invalid_environment_value_is_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="prod")  # typo must fail validation, not silently pass
