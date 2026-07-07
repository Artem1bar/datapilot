# DataPilot

![Tests](https://github.com/Artem1bar/datapilot/actions/workflows/test.yml/badge.svg)

An AI-powered data cleaning and analysis platform. Upload a CSV, Excel, or Parquet file, describe what you want in plain language, and DataPilot's AI agent inspects your data, proposes a cleaning plan, applies it, and lets you export the result.

**Live:** [datapilot-eight.vercel.app](https://datapilot-eight.vercel.app)

## Features

- **AI-driven cleaning** — Claude inspects your dataset, infers the schema, and proposes a structured cleaning plan (null handling, type coercion, deduplication, outlier removal, etc.)
- **Chat-first UI** — conversational interface for uploading files, reviewing plans, and applying transformations; no SQL or code required
- **Workflow stepper** — visual step-by-step progress through Inspect → Plan → Clean → Validate
- **Data manipulation** — filter, rename, pivot, aggregate, and transform columns via natural language
- **Multi-sheet support** — handles Excel workbooks with multiple sheets
- **Cleaning recipes** — save a cleaning plan as a reusable template and apply it to new datasets in one click
- **AI data dictionary** — auto-generate a column-level data dictionary with field descriptions, types, and quality notes
- **Data visualizations** — ask questions in chat and Claude returns charts (bar, line, pie, scatter) rendered live in a slide-out panel
- **Cleaned dataset library** — all processed datasets are stored and can be re-downloaded at any time
- **Export** — download cleaned files as CSV, Excel, or Parquet
- **Live progress** — polled job updates so you see cleaning progress as it happens

## Architecture

```
apps/
├── web/                # React + Vite frontend
│   └── src/
│       ├── components/ # Chat, workflow stepper, dataset library
│       ├── pages/      # Chat, CleanedDatasets, Settings
│       └── stores/     # Zustand state (sessions, workflow, app)
└── api/                # FastAPI backend
    └── app/
        ├── routers/    # REST endpoints (cleaning, datasets, jobs, manipulation, export, recipes, dictionary)
        ├── services/   # AI agent, schema inference, cleaning execution, storage
        ├── models/     # SQLAlchemy ORM (Dataset, Job)
        └── tasks/      # Background job workers

packages/               # Shared TypeScript types
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite, TypeScript, Tailwind CSS, Framer Motion |
| Backend | Python, FastAPI, SQLAlchemy (async), Alembic |
| AI | Anthropic Claude — Opus 4.8 (cleaning plan), Sonnet 4.6 (manipulation, verification), Haiku 4.5 (analysis, dictionary) |
| Auth | Clerk |
| Storage | MinIO / Cloudflare R2 (file storage) |
| Database | PostgreSQL |
| Cache / Pub-Sub | Redis |
| Deployment | Vercel (frontend), Docker Compose (backend) |

## Privacy & data handling

Uploaded files are processed by Anthropic's Claude API: a sample of rows and
the column profile are sent to Claude to generate cleaning plans, run
verification, answer analysis questions, and build data dictionaries. Data is
not used to train models (see [Anthropic's data usage policy](https://www.anthropic.com/legal/commercial-terms)).

Files are stored in your configured object storage (MinIO/R2) and deleting a
dataset cascades to remove its stored objects; a daily job also purges orphaned
uploads. Do not upload data you are not permitted to send to a third-party API.

## Local Development

### Prerequisites

- Node.js 20+, pnpm
- Python 3.12+, uv
- Docker (for Postgres, Redis, MinIO)

### Setup

```bash
# 1. Clone and install JS dependencies
git clone https://github.com/Artem1bar/datapilot.git
cd datapilot
pnpm install

# 2. Start infrastructure
docker-compose up -d

# 3. Configure environment
cp .env.example .env
# Required: ANTHROPIC_API_KEY
# For production auth: CLERK_JWT_ISSUER, CLERK_WEBHOOK_SECRET (and set DEV_AUTH_BYPASS=false)

# 4. Install Python dependencies and run migrations
cd apps/api
uv sync
uv run alembic upgrade head

# 5. Start the API server
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 6. Start the frontend (in a separate terminal)
cd ../..
pnpm dev:web
```

The app will be available at `http://localhost:5173`.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key for the AI cleaning agent |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `R2_ENDPOINT_URL` | MinIO/R2 endpoint for file storage |
| `R2_ACCESS_KEY_ID` | Storage access key |
| `R2_SECRET_ACCESS_KEY` | Storage secret key |
| `CLERK_JWT_ISSUER` | Clerk Frontend API URL / JWT issuer (production auth) |
| `CLERK_WEBHOOK_SECRET` | Svix signing secret for Clerk user-sync webhooks |
| `DEV_AUTH_BYPASS` | `true` locally to skip auth; ignored in production |

## Tests

**566 tests total** (455 backend + 111 frontend).

### Backend (455 tests) — run from `apps/api/`

```bash
cd apps/api
uv run pytest
```

| File | What it covers |
|------|---------------|
| `test_cleaning_task.py` | AI cleaning plan generation and application (core agent) |
| `test_cleaning_operations.py` | Null handling, type coercion, deduplication, outlier removal |
| `test_verification_agent.py` | Post-cleaning validation and quality checks |
| `test_schema_inference.py` | Column type inference from raw data |
| `test_manipulation_executor.py` | Filter, rename, pivot, aggregate transformations |
| `test_analysis.py` | Chat-based AI data analysis and visualization |
| `test_dictionary.py` | AI data dictionary generation |
| `test_recipes.py` | Cleaning recipe save, load, and apply |
| `test_export.py` | CSV/Excel/Parquet export jobs |
| `test_storage.py` | File storage (upload, download, delete) |
| `test_comparison.py` | Dataset version comparison |
| `test_jobs.py` | Job status polling |
| `test_auth.py` | Clerk webhook authentication |
| `test_multi_sheet.py` | Excel multi-sheet handling |
| `test_file_validation.py` | Upload format and size validation |
| `test_outlier_thresholds.py` | Outlier detection boundary conditions |
| `test_verification.py` | Cleaning verification logic |
| `test_health.py` | API health endpoint |
| `test_history.py` | History entry creation, UUID uniqueness, metadata isolation |
| `test_plan_validator.py` | Pre-execution plan validation (unknown ops, missing columns, bad params) |
| `test_plan_generation.py` | Plan generate → validate → regenerate-on-invalid loop |
| `test_datasets_router.py` | Dataset download/delete endpoints, JSON-safe previews |
| `test_progress_reporting.py` / `test_task_db.py` | Per-stage job progress persistence, shared worker DB engine |
| `test_structured_output.py` | Forced-tool-use helper: rate-limit retries, confidence coercion, error paths |
| `test_auth_jwt.py` | Clerk session-JWT verification (JWKS/RS256, issuer + expiry, bypass rules) |
| `test_ownership.py` | Cross-user isolation — user B requesting user A's resources gets 404 |
| `test_settings.py` / `test_cleaning_plan_prefs.py` | User-preferences `/settings` API and prefs threaded into plan generation |
| `test_upload_validation.py` | Upload size cap + magic-byte validation on the upload routes |
| `test_export_sanitization.py` | CSV/Excel formula-injection sanitization on export |
| `test_data_driven_caps.py` / `test_domain_detection.py` | Percentile-based caps and domain gating (survey/expense heuristics off by default) |
| `test_ai_budget.py` / `test_ai_endpoint_rate_limits.py` | AI kill-switch, per-user daily budget, and rate limits on open AI endpoints |
| `test_cleanup_task.py` | Daily orphaned-upload purge (data lifecycle) |
| `test_app_boot.py` | App wiring smoke test — routers mounted, middleware installed |

### Frontend (111 tests) — run from `apps/web/`

```bash
cd apps/web
pnpm test              # or: pnpm test:coverage
```

| File | What it covers |
|------|---------------|
| `src/lib/utils.test.ts` | `cn()` Tailwind class-merge utility |
| `src/lib/intent.test.ts` | Chat intent routing (clean/manipulate/analyze/report/chat) + precedence |
| `src/lib/progress.test.ts` | Cleaning progress → stage-label thresholds |
| `src/lib/upload.test.ts` | Client-side upload validation (size cap, accepted types) |
| `src/stores/app-store.test.ts` | Sidebar, chart panel, chart list, and theme state |
| `src/stores/session-store.test.ts` | Session CRUD, messages, workflow step transitions |
| `src/components/cards/CleaningPlanCard.test.tsx` | Plan card rendering, step display, accept/reject actions |
| `src/components/cards/ErrorCard.test.tsx` | Error card rendering + retry re-dispatch |
| `src/components/chat/ChatStream.test.tsx` | Message stream rendering |
| `src/components/settings/CleaningSettings.test.tsx` | Cleaning settings form wired to the `/settings` API |

## API Overview

| Endpoint | Description |
|----------|-------------|
| `POST /datasets/upload` | Upload a CSV/Excel/Parquet file and create a dataset |
| `GET /datasets/` | List all datasets |
| `GET /datasets/{id}` | Get dataset metadata |
| `GET /datasets/{id}/preview` | Preview dataset rows and column stats |
| `GET /datasets/{id}/schema` | Get inferred column schema |
| `GET /datasets/{id}/history` | Dataset version history |
| `POST /cleaning/{id}/plan` | Generate an AI cleaning plan |
| `POST /cleaning/{id}/apply` | Apply a cleaning plan (async job) |
| `GET /cleaning/{id}/plan` | Retrieve the current cleaning plan |
| `GET /cleaning/{job_id}/verification` | Get post-cleaning validation report |
| `POST /manipulation/{id}/parse` | Preview a data manipulation operation |
| `POST /manipulation/{id}/apply` | Apply a data manipulation operation |
| `POST /manipulation/{id}/undo` | Undo the last manipulation |
| `POST /exports/{id}` | Start an export job (CSV, Excel, Parquet) |
| `GET /exports/{job_id}/download` | Download the exported file |
| `GET /datasets/{id}/dictionary` | Auto-generate AI data dictionary |
| `GET /jobs/{id}` | Poll job status and results |
| `GET /recipes/` | List saved cleaning recipes |
| `POST /recipes/` | Save a new cleaning recipe |
| `GET /recipes/{id}` | Get a specific recipe |
| `POST /recipes/{id}/apply` | Apply a recipe to a dataset |
| `DELETE /recipes/{id}` | Delete a recipe |
| `POST /datasets/{id}/compare/{other_id}` | Compare two dataset versions |
| `POST /datasets/{id}/chat` | Send a chat message for AI analysis |
| `GET /datasets/{id}/sessions` | List chat sessions for a dataset |
