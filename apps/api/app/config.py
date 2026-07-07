from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # datapilot/
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # shell empty-string overrides don't shadow .env values
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://datapilot:datapilot@localhost:5432/datapilot"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO / R2
    R2_ENDPOINT_URL: str = "http://localhost:9000"
    R2_ACCESS_KEY_ID: str = "minioadmin"
    R2_SECRET_ACCESS_KEY: str = "minioadmin"
    R2_BUCKET_NAME: str = "datapilot"

    # Clerk
    CLERK_SECRET_KEY: str = ""
    CLERK_PUBLISHABLE_KEY: str = ""
    # Svix signing secret for Clerk webhooks (starts with "whsec_").
    CLERK_WEBHOOK_SECRET: str = ""
    # Clerk Frontend API URL / JWT issuer, e.g. https://xxx.clerk.accounts.dev.
    # Session JWTs are verified against {issuer}/.well-known/jwks.json.
    CLERK_JWT_ISSUER: str = ""

    # Auth: when true (and NOT production) every request resolves to a local dev
    # user with no token. Ignored in production, which always requires a JWT.
    DEV_AUTH_BYPASS: bool = True

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Anthropic model tiers, per pipeline stage. Defaults preserve the models
    # each stage historically used; override any of them via env.
    CLEANING_MODEL: str = "claude-opus-4-8"
    VERIFICATION_MODEL: str = "claude-sonnet-4-6"
    MANIPULATION_MODEL: str = "claude-sonnet-4-6"
    ANALYSIS_MODEL: str = "claude-haiku-4-5-20251001"
    DICTIONARY_MODEL: str = "claude-haiku-4-5-20251001"

    # Uploads — reject files larger than this (bytes). Default 50 MB.
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024

    # CORS
    CORS_ORIGINS: str = "http://localhost:5174"

    # Deployment. Typed so a typo (e.g. "prod") fails validation at startup
    # rather than silently re-enabling the dev auth bypass.
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    def production_secret_problems(self) -> list[str]:
        """List insecure-default or missing secrets when ENVIRONMENT=production.

        Empty outside production or when everything is configured — the app
        refuses to start if this returns anything in production.
        """
        if self.ENVIRONMENT != "production":
            return []
        problems: list[str] = []
        if self.R2_ACCESS_KEY_ID == "minioadmin":
            problems.append("R2_ACCESS_KEY_ID is the insecure default 'minioadmin'")
        if self.R2_SECRET_ACCESS_KEY == "minioadmin":
            problems.append("R2_SECRET_ACCESS_KEY is the insecure default 'minioadmin'")
        if "datapilot:datapilot@localhost" in self.DATABASE_URL:
            problems.append("DATABASE_URL uses the default local credentials")
        if not self.ANTHROPIC_API_KEY:
            problems.append("ANTHROPIC_API_KEY is not set")
        if not self.CLERK_JWT_ISSUER:
            problems.append("CLERK_JWT_ISSUER is not set (auth would reject every request)")
        if not self.CLERK_WEBHOOK_SECRET:
            problems.append("CLERK_WEBHOOK_SECRET is not set (webhooks would be rejected)")
        if self.DEV_AUTH_BYPASS:
            problems.append("DEV_AUTH_BYPASS must be false in production")
        return problems


settings = Settings()
