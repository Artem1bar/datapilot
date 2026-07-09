"""Real-services integration fixtures for the DataPilot API.

Unlike the mocked suite in ``tests/``, everything here runs against a real
Postgres database (``datapilot_test``) and the local Redis, through the actual
FastAPI app and Celery task code paths. The whole directory is skipped unless
``INTEGRATION_TESTS=1`` is set, so the default ``uv run pytest`` run needs no
services.

Environment bootstrapping happens at import time, BEFORE any ``app.*`` module
is imported: ``app.config.settings`` is a module-level singleton and
``app.db.engine.engine`` is built from it on first import. When
``INTEGRATION_TESTS=1`` and no explicit ``DATABASE_URL``/``REDIS_URL`` is
exported, defaults are derived here — the database name from the repo-root
``.env`` URL with the name swapped to ``datapilot_test``, and Redis db 1
(instead of the dev db 0). A hard guard aborts the run if the effective
database name does not end in ``_test``, so the developer's real ``datapilot``
database can never be migrated or truncated by this suite.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL

_INTEGRATION_DIR = Path(__file__).resolve().parent
_API_DIR = _INTEGRATION_DIR.parents[1]  # apps/api
_REPO_ROOT = _API_DIR.parents[1]  # datapilot/
_TEST_DB_NAME = "datapilot_test"
_TEST_REDIS_URL = "redis://localhost:6379/1"
_FALLBACK_DB_URL = "postgresql+asyncpg://datapilot:datapilot@localhost:5432/datapilot"

RUN_INTEGRATION = os.environ.get("INTEGRATION_TESTS") == "1"
SKIP_REASON = "integration tests are opt-in: set INTEGRATION_TESTS=1 (needs Postgres + Redis)"


def _default_test_database_url() -> str:
    """The repo-root ``.env`` DATABASE_URL with the database swapped to _test.

    Reuses the developer's real credentials/host but never their database.
    Parsed by hand (not via ``app.config``) because importing ``app.config``
    is exactly what this bootstrap must pre-empt.
    """
    raw = _FALLBACK_DB_URL
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                raw = line.split("=", 1)[1].strip()
    url = make_url(raw).set(database=_TEST_DB_NAME)
    return url.render_as_string(hide_password=False)


if RUN_INTEGRATION:
    # Must run before the first `import app.*` anywhere in this process.
    os.environ.setdefault("DATABASE_URL", _default_test_database_url())
    os.environ.setdefault("REDIS_URL", _TEST_REDIS_URL)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip everything under tests/integration unless INTEGRATION_TESTS=1."""
    if RUN_INTEGRATION:
        return
    skip_marker = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if _INTEGRATION_DIR in item.path.parents:
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# Session-scoped database bootstrap (guard, create-if-missing, migrate)
# ---------------------------------------------------------------------------


def _ensure_database_exists(async_url: URL) -> None:
    """Create the test database if it is missing; explain how if we can't."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.pool import NullPool

    sync_url = async_url.set(drivername="postgresql+psycopg2")
    try:
        with create_engine(sync_url, poolclass=NullPool).connect():
            return
    except OperationalError as exc:
        if "does not exist" not in str(exc):
            raise
    admin_url = sync_url.set(database="postgres")
    try:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{async_url.database}"'))
    except Exception as exc:
        raise RuntimeError(
            f"Could not create the integration test database '{async_url.database}'. "
            "Create it manually, e.g.: psql -h localhost -U <superuser> -d postgres "
            f"-c 'CREATE DATABASE {async_url.database} OWNER {async_url.username}'"
        ) from exc


def _run_migrations() -> None:
    """Programmatic ``alembic upgrade head`` against settings.DATABASE_URL.

    alembic/env.py injects ``settings.DATABASE_URL`` over the ini default, so
    the migrations land in the same test database the app engine uses.
    """
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(_API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Validate the target database, create it if needed, and migrate to head."""
    from app.config import settings

    env_url = os.environ.get("DATABASE_URL", "")
    if settings.DATABASE_URL != env_url:
        pytest.exit(
            "app.config was imported before the integration DATABASE_URL was set "
            f"(settings has {make_url(settings.DATABASE_URL).database!r}). Run with an "
            "explicit DATABASE_URL env var, e.g. "
            "INTEGRATION_TESTS=1 DATABASE_URL=postgresql+asyncpg://...datapilot_test "
            "uv run pytest tests/integration",
            returncode=1,
        )

    url = make_url(settings.DATABASE_URL)
    if not (url.database or "").endswith("_test"):
        pytest.exit(
            f"Refusing to run integration tests against database {url.database!r}: "
            "the name must end with '_test' (these tests TRUNCATE every table).",
            returncode=1,
        )

    _ensure_database_exists(url)
    _run_migrations()
    return settings.DATABASE_URL


# ---------------------------------------------------------------------------
# Per-test isolation
# ---------------------------------------------------------------------------


@pytest.fixture
async def _fresh_database(_migrated_database: str):
    """Truncate all app tables before each test; dispose pools after it.

    Truncation runs at setup (not teardown) so rows leaked by an aborted
    previous run can't contaminate this one. Disposing the async engine after
    every test is load-bearing: pytest-asyncio gives each test its own event
    loop, and pooled asyncpg connections are bound to the loop that created
    them — a connection reused across loops fails. Same story for the two
    module-level async Redis pools.
    """
    import app.models  # noqa: F401 — register every table on Base.metadata
    from app.db.base import Base
    from app.db.engine import engine

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    yield

    from app.services.progress import close_redis
    from app.services.rate_limit import close_redis_pool

    await close_redis()
    await close_redis_pool()
    await engine.dispose()


@pytest.fixture
async def db_session(_fresh_database: None):
    """A real AsyncSession on the app's engine, against the migrated test DB."""
    from app.db.engine import async_session

    async with async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Seeded rows and an authenticated app client
# ---------------------------------------------------------------------------


async def _create_user(db_session, prefix: str):
    from app.models.user import User

    marker = uuid.uuid4().hex[:12]
    user = User(
        id=uuid.uuid4(),
        clerk_id=f"{prefix}_{marker}",
        email=f"{prefix}-{marker}@integration.test",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_user(db_session):
    """A persisted user row the API client authenticates as."""
    return await _create_user(db_session, "it_user")


@pytest.fixture
async def other_user(db_session):
    """A second persisted user, for ownership/404 tests."""
    return await _create_user(db_session, "it_other")


@pytest.fixture
def make_dataset(db_session):
    """Factory for persisted Dataset rows owned by a given user."""

    async def _make(
        owner,
        *,
        filename: str = "orders.csv",
        status: str = "uploaded",
        profile_json: dict | None = None,
    ):
        from app.models.dataset import Dataset

        dataset = Dataset(
            id=uuid.uuid4(),
            user_id=owner.id,
            filename=filename,
            r2_key=f"uploads/{owner.id}/{uuid.uuid4().hex}-{filename}",
            file_size_bytes=1234,
            status=status,
            profile_json=profile_json,
        )
        db_session.add(dataset)
        await db_session.commit()
        await db_session.refresh(dataset)
        return dataset

    return _make


@pytest.fixture
async def client(test_user):
    """httpx AsyncClient against the real app; only auth is overridden.

    ``get_db`` stays real, so requests exercise the app's actual engine,
    session wiring, and JSONB serialization against the test database.
    """
    from httpx import ASGITransport, AsyncClient

    from app.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http
    finally:
        app.dependency_overrides.pop(get_current_user, None)
