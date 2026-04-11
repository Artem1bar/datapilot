from pathlib import Path

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

    # Supabase (optional — replaces Clerk auth + provides DB + storage)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:5174"

    # Deployment
    ENVIRONMENT: str = "development"  # development | staging | production

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


settings = Settings()
