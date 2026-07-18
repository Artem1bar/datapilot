# Integration tests (real services)

Opt-in tests that run against a **real Postgres database and the local Redis**
through the actual FastAPI app and Celery task code paths — no mocks. They are
skipped entirely unless `INTEGRATION_TESTS=1` is set, so the default
`uv run pytest` stays green with no services beyond what the mocked suite uses.

## Requirements

- Postgres on `localhost:5432` with a database whose name ends in `_test`
  (default: `datapilot_test`). Create it once:

  ```bash
  psql -h localhost -U <superuser> -d postgres \
    -c "CREATE DATABASE datapilot_test OWNER datapilot"
  ```

  (The conftest also attempts to create it automatically if the configured
  DB user has `CREATEDB`.)
- Redis on `localhost:6379` (db 1 is used by default, keeping the dev db 0 clean).
- MinIO is **not** required — storage-dependent paths are out of scope here.

## Running

```bash
cd apps/api
INTEGRATION_TESTS=1 \
  DATABASE_URL=postgresql+asyncpg://datapilot:<password>@localhost:5432/datapilot_test \
  uv run pytest tests/integration -q
```

`DATABASE_URL` is optional locally: when it isn't exported, the conftest derives
it from the repo-root `.env` by swapping the database name to `datapilot_test`
(same credentials/host). Passing it explicitly is required in CI and whenever
`app.config` might be imported before this directory's conftest (e.g. running
the full suite with `INTEGRATION_TESTS=1 uv run pytest`).

## Safety

- A hard guard aborts the run unless the effective database name ends in
  `_test` — the developer's real `datapilot` database is never touched.
- Migrations (`alembic upgrade head`) run once per session, programmatically.
- Every app table is `TRUNCATE ... CASCADE`-d before each test, so tests are
  independent and re-runnable.

## Layout

| File | Covers |
| --- | --- |
| `conftest.py` | env bootstrap, skip logic, DB create+migrate, truncation, seeded users, authenticated `httpx` client (auth is the only dependency override — `get_db` is real) |
| `test_datasets_crud.py` | dataset list/get/delete round-trips, ownership 404s |
| `test_jobs_and_recipes_crud.py` | job reads, recipe CRUD, apply-validation 422 (hits real Redis rate limiting) |
| `test_celery_task_roundtrip.py` | `reap_stale_jobs` in Celery eager mode via the sync engine |
