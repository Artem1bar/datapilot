# Changelog

All notable changes to DataPilot are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

- Backend deployment pending (Railway + Clerk + R2 provisioning required — see `docs/DEPLOYMENT.md`).

---

## [0.5.0] — 2026-08-15

### Fixed
- Remove duplicate `ManipulationError` import; correct `_validate_drop_rows` return type annotation.

### Tests
- HTTP-layer tests for exports router — create, presigned download URL, 404/400/500 paths.
- HTTP-layer tests for analysis router chat-session endpoints (list, get, 404).
- `test_manipulation_service.py` — `generate_preview`, `_dataframe_to_bytes`, `parse_manipulation_intent` helpers.
- `test_analysis.py` expanded — `_read_sample_rows` coverage for all file format branches (CSV, Excel, Parquet).
- `test_rate_limit_sliding_window.py` — Redis sliding-window pipeline calls, TTL padding, reject-without-counting at limit.
- Added 8 previously undocumented backend test files to README test table.
- Backend total: **619 tests** (up from 559 in 0.4.0).

---

## [0.4.0] — 2026-08-06

### Added
- Missing environment variables documented in README table.
- Replaced Vite boilerplate with DataPilot-specific content in `apps/web/README.md`.

### Fixed
- Ruff import sort (`I001`) in `storage.py`.
- Silenced mypy `call-overload` error on Anthropic `client.messages.create`.

### Tests
- HTTP-layer tests for manipulation router (18 tests).
- HTTP-layer tests for cleaning router (18 tests).
- Backend total: 313 backend + 246 service/router = **559 tests**.

---

## [0.3.0] — 2026-07-18 — Launch Readiness

### Added
- **Sentry error tracking** — no-op without `SENTRY_DSN`; activates on env var.
- **Railway deploy job** — `.github/workflows/test.yml` includes E2E against provisioned services.
- **E2E suite** — 3 Playwright specs: golden path, session binding, refresh re-attach.
- **Real-services integration suite** — 13 tests behind `INTEGRATION_TESTS=1`, hitting MinIO + real DB.
- **MinIO** service container in CI (`docker run`, health-checked before test run).
- **Stale-job reaper** — background task purges jobs stuck in `pending`/`running` > 1h.
- **Export retention** — cleaned files preserved for 7 days; purge-protection guard.
- **"Try with sample data"** button on empty state for onboarding.
- **Trust UX on cleaning results** — "see what changed", revert, save-as-recipe, recipe picker.
- **Cleaning revert** — `POST /cleaning/{job_id}/revert` endpoint; per-job cleaned-file keys.
- **Before/after comparison** — parseable side-by-side diff for cleaning results.
- **Re-attach to running jobs** after page refresh.
- **Table paste** → CSV upload; `POST /datasets/paste` endpoint.
- **Shared version selection** — `GET /cleaning/versions` for selecting between multiple cleans.

### Fixed
- DataTiger → DataPilot branding (hero, sidebar wordmark, footer, page title).
- `pandas`/`numpy`-aware JSON serializer on both DB engine types.
- Arrow/object dtype comparison in `_diff_column`.
- Run comparison parse+diff off the event loop (asyncio).

### Tests
- 45 unit tests for comparison and analysis service helpers.
- 66 unit tests for manipulation executor pure DataFrame operations.
- 23 unit tests for schema inference.
- 7 unit tests for data dictionary generator.
- 21 unit tests for multi-sheet service.
- 3 health endpoint tests.

---

## [0.2.0] — 2026-06-01 — Feature Complete

### Added
- **AI-driven cleaning** — Claude inspects dataset, infers schema, proposes structured plan.
- **Chat-first UI** — conversational interface; no SQL or code required.
- **Workflow stepper** — visual step-by-step: Inspect → Plan → Clean → Validate.
- **Data manipulation** — filter, rename, pivot, aggregate via natural language.
- **Multi-sheet Excel** support — handles workbooks with multiple sheets.
- **Cleaning recipes** — save a plan as a reusable template; apply to new datasets in one click.
- **AI data dictionary** — auto-generate column-level descriptions, types, quality notes.
- **Data visualizations** — chat-triggered charts (bar, line, pie, scatter) in a slide-out panel.
- **Cleaned dataset library** — all processed datasets stored and re-downloadable.
- **Export** — CSV, Excel, or Parquet.
- **Live progress** — polled job updates show cleaning progress in real time.
- CI workflow (GitHub Actions) — lint + tests + E2E.
- Frontend lint (ESLint + TypeScript type check).
- Prompt caching on large static prompts (dictionary, analysis).

### Fixed
- All ruff/ESLint/mypy issues in initial codebase.

---

## [0.1.0] — 2026-05-01 — Initial Commit

- Initial DataPilot AI data cleaning platform.
- React + Vite frontend, FastAPI backend, SQLAlchemy + Alembic.
- Claude integration for schema inference and cleaning.
- S3-compatible storage (R2), PostgreSQL, Celery background jobs.
