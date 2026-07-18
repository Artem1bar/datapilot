# Deploying DataPilot (Railway + Cloudflare R2 + Vercel + Clerk)

_Host decisions locked 2026-07-09: backend on **Railway**, storage on **Cloudflare R2**, frontend stays on **Vercel**, auth is **Clerk** (invite-only private beta)._

The code side is done: multi-stage Dockerfile (api + worker), host-agnostic
`deploy.yml` with a Railway deploy job, prod fail-fast config guards, CORS/CSP
wiring, structured logs. What remains is **provisioning** — every step below
is an account/dashboard action only the project owner can do.

## 1. Railway (api + worker + Postgres + Redis)

1. Create a Railway project; add plugins: **PostgreSQL** and **Redis**.
2. Create two services from this repo (root directory `apps/api`, it has the Dockerfile):
   - **api** — start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **worker** — start command: `celery -A app.tasks.celery_app worker -B --loglevel=info`
     (`-B` embeds the beat scheduler: daily storage cleanup, export retention, stale-job reaper. Run exactly one worker instance with `-B`.)
3. Set the shared environment variables on both services:

   | Variable | Value |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `DEV_AUTH_BYPASS` | `false` |
   | `DATABASE_URL` | Railway Postgres URL, changed to `postgresql+asyncpg://…` |
   | `REDIS_URL` | Railway Redis URL |
   | `ANTHROPIC_API_KEY` | production key (set a spend limit in the Anthropic console) |
   | `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET_NAME` | from step 2 below |
   | `CLERK_JWT_ISSUER` | `https://<your-clerk-frontend-api>` (from Clerk dashboard) |
   | `CLERK_WEBHOOK_SECRET` | from the Clerk webhook endpoint (step 4) |
   | `CORS_ORIGINS` | your Vercel production URL |
   | `AI_ENABLED` | `true` |

   The app **fails fast at boot** if `ENVIRONMENT=production` and any secret
   is missing or still a known dev default — an api service that boots is a
   correctly configured one.
4. GitHub repo secrets for the deploy workflow:
   - `RAILWAY_TOKEN` — a Railway **project token** (deploy job skips gracefully while unset)
   - `DATABASE_URL` — same as above (used by the migration job)

## 2. Cloudflare R2

1. Create a bucket (e.g. `datapilot-prod`). Keep it **private** — all
   downloads stream through the API, nothing is served from the bucket directly.
2. Create an R2 API token with object read/write on that bucket.
3. Fill the `R2_*` variables on both Railway services. `config.py` is already
   R2-shaped (endpoint derived from the account id); MinIO is dev-only.

## 3. Vercel (frontend)

1. Project env vars (Production):
   - `VITE_API_URL` = the Railway api service's public URL
   - `VITE_CLERK_PUBLISHABLE_KEY` = Clerk production publishable key
2. `vercel.json` CSP: the `connect-src` already includes a placeholder API
   origin — replace it with the Railway api URL.
3. Redeploy after env changes (Vercel only bakes `VITE_*` at build time).

## 4. Clerk (invite-only private beta)

1. Create the production Clerk instance; copy the publishable key (→ Vercel)
   and the **JWT issuer** URL (→ Railway `CLERK_JWT_ISSUER`).
2. Restrict sign-ups: Clerk dashboard → *User & Authentication → Restrictions*
   → **Invitation-only** mode. Invite beta users by email from the dashboard.
3. Add a webhook endpoint pointing at `https://<railway-api>/api/v1/auth/webhook`
   (events: `user.created`, `user.deleted`); copy its signing secret
   (→ Railway `CLERK_WEBHOOK_SECRET`). The handler is svix-verified and fail-closed.
4. **Live sign-in QA** (still pending — needs this instance): sign in through
   the deployed frontend, upload → clean → download, then verify a second
   account cannot see the first account's datasets.

## 5. Sentry (optional but recommended before launch)

The `sentry-sdk[fastapi]` dependency is installed and the init wiring is live
in `app/main.py` (`_init_sentry()` — no-op when `SENTRY_DSN` is unset).

To activate: create a Sentry project (FastAPI / Python) → copy the DSN → set
`SENTRY_DSN=https://…@…sentry.io/…` on both Railway services (api + worker).
The Celery integration is not yet wired — add `sentry_sdk.integrations.celery.CeleryIntegration`
in `app/tasks/celery_app.py` if you also want worker errors captured.

## 6. Launch checklist

- [ ] Railway api + worker deployed, healthcheck green (`GET /health`)
- [ ] `alembic upgrade head` ran against prod Postgres (deploy workflow does this)
- [ ] Vercel frontend points at the Railway API; upload → clean → export works on the production URL
- [ ] Clerk invitation-only mode on; live sign-in QA done (incl. cross-user 404 check)
- [ ] Anthropic key has a spend cap; `AI_ENABLED` kill-switch understood
- [ ] Railway Postgres backups enabled (dashboard toggle)
- [ ] Sentry receiving events (or consciously deferred)
- [ ] Rollback rehearsed once: redeploy the previous Railway deployment from the dashboard
- [ ] Data retention live: exports purge after 7 days, orphaned uploads after 24 h (beat tasks — check worker logs for `Storage cleanup:` / `Export retention:` lines)

## Rollback

`railway redeploy` (dashboard or CLI) restores the previous deployment.
Images are also pushed to GHCR tagged by commit SHA by the deploy workflow,
so any past version can be redeployed by tag. Migrations are additive so far;
if a migration must be reverted, `alembic downgrade -1` against prod DB.
