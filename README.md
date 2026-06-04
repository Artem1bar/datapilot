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
- **Cleaned dataset library** — all processed datasets are stored and can be re-downloaded at any time
- **Export** — download cleaned files as CSV, Excel, or Parquet
- **Real-time progress** — WebSocket-streamed job updates so you see cleaning progress live

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
supabase/               # Auth and DB migrations
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, Framer Motion |
| Backend | Python, FastAPI, SQLAlchemy (async), Alembic |
| AI | Anthropic Claude (cleaning agent, schema inference, verification) |
| Auth | Supabase Auth / Clerk |
| Storage | MinIO / Cloudflare R2 (file storage) |
| Database | PostgreSQL |
| Cache / Pub-Sub | Redis |
| Deployment | Vercel (frontend), Docker Compose (backend) |

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
# Required: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY

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
| `SUPABASE_URL` | Supabase project URL (auth) |
| `SUPABASE_ANON_KEY` | Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key |

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
| `WS /ws/jobs/{job_id}` | Real-time job progress stream |
