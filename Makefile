.PHONY: dev dev-services dev-api dev-web migrate seed test lint

# Start all Docker Compose services
dev-services:
	docker compose up -d

# Start the API server (requires services running)
dev-api:
	cd apps/api && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start the Celery worker
dev-worker:
	cd apps/api && uv run celery -A app.tasks.celery_app worker --loglevel=info

# Start the frontend dev server
dev-web:
	cd apps/web && pnpm dev

# Start everything
dev:
	docker compose up -d
	@echo "Services started. Run 'make dev-api', 'make dev-worker', and 'make dev-web' in separate terminals."

# Run Alembic migrations
migrate:
	cd apps/api && uv run alembic upgrade head

# Generate a new migration
migration:
	cd apps/api && uv run alembic revision --autogenerate -m "$(msg)"

# Seed the database
seed:
	cd apps/api && uv run python -m app.db.seed

# Run all tests
test:
	cd apps/api && uv run pytest
	cd apps/web && pnpm test

# Lint
lint:
	cd apps/api && uv run ruff check .
	cd apps/web && pnpm lint

# Install all dependencies
install:
	cd apps/api && uv sync
	cd apps/web && pnpm install
