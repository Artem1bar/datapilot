#!/usr/bin/env bash
# Starts the backend half of the E2E stack: dedicated Postgres database,
# migrations, Celery worker, and the API on :8001 — all pointed at the
# stub Anthropic server. Playwright launches this via webServer and
# terminates it when the run ends; the trap takes the worker down with it.
set -euo pipefail

cd "$(dirname "$0")/../apps/api"

export E2E_API_PORT="${E2E_API_PORT:-8001}"
export DATABASE_URL="${E2E_DATABASE_URL:-postgresql+asyncpg://$(whoami)@localhost:5432/datapilot_e2e}"
export REDIS_URL="${E2E_REDIS_URL:-redis://localhost:6379/1}"
export ANTHROPIC_BASE_URL="${E2E_STUB_URL:-http://localhost:9797}"
export ANTHROPIC_API_KEY="stub-key"
export DEV_AUTH_BYPASS=true
export AI_ENABLED=true
export ENVIRONMENT=development

# Fresh database per run: jobs/datasets from the previous run would otherwise
# leak into assertions (e.g. recipe lists).
DB_NAME="${DATABASE_URL##*/}"
PSQL="psql -h localhost -d postgres -v ON_ERROR_STOP=1 -qAt"
if [ -n "${E2E_DB_SUPERUSER:-}" ]; then
  PSQL="psql -h localhost -U ${E2E_DB_SUPERUSER} -d postgres -v ON_ERROR_STOP=1 -qAt"
fi
$PSQL -c "DROP DATABASE IF EXISTS ${DB_NAME}" || true
$PSQL -c "CREATE DATABASE ${DB_NAME}"

uv run alembic upgrade head

uv run celery -A app.tasks.celery_app worker --loglevel=warning --pool=threads --concurrency=2 &
WORKER_PID=$!

cleanup() {
  kill "$WORKER_PID" 2>/dev/null || true
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv run uvicorn app.main:app --host 127.0.0.1 --port "$E2E_API_PORT" &
API_PID=$!

wait "$API_PID"
