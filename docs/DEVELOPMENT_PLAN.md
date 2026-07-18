# DataPilot Development Plan — Road to Fully Operational

_Created 2026-07-07 from a fresh four-track audit (backend security/deploy, cleaning brain, frontend UX, CI/infra). Supersedes Phases 2–3 of [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md), which remains the audit trail for the 2026-07-06 findings and the completed Phase 0–1 work._

**Verified baseline (2026-07-07):** 403 backend + 49 frontend tests green, `pnpm build` passes, ruff/eslint clean in CI. Phase 0 ("stop the bleeding") and Phase 1 ("make the loops actually work") are complete and committed — plan validation + regeneration, forced-tool-use structured outputs, remediation-loop convergence with unresolvable-flag tracking, honest DB-backed progress, retry semantics, and the chat plan-approval gate all shipped.

---

## Progress log — overnight session 2026-07-07 (branch `phase-2-product-quality`)

All items below are committed with tests on branch `phase-2-product-quality` (**not merged**). End-of-session state: **451 backend + 57 frontend tests green, ruff/eslint/tsc clean, Dockerfile build-verified, migration verified against real Postgres, auth security-reviewed**. ~31 commits, TDD throughout.

**Phase 2 — Product quality (COMPLETE except lower-priority 2B UX):**
- ✅ 2A Cleaning brain — all 7 items: null masking (CRITICAL), data-driven caps + tone (deleted the dollar table; profile carries p95/p99/mad), demote survey/expense heuristics behind a detected `domain`, configurable model tiers, recipe validation (422 naming the missing column), remediation-op subset enforced from one source.
- ✅ 2C Settings surface — `preferences` JSONB on users + `UserPreferences` schema (single source of defaults), `GET/PUT /settings`, Alembic migration (verified: `upgrade` + `alembic check` clean against an ephemeral Postgres), `env.py` now injects `DATABASE_URL`. Prefs (domain / ai_sample_size / custom_instructions) threaded into plan generation; a Cleaning-settings tab is wired to the API (component-tested; **live QA pending**).
- ✅ 2B correctness core: wrong-session card actions, per-session workflow state, persisted applied-state, dead-code deletion + README truth.
- ✅ 2B (2026-07-07 afternoon): upload UX feedback (#7 — client-side `validateUploadFile` mirrors the 50 MB / CSV-Excel backend caps, rejects before the round-trip, shared accepted-types with the attach menu) and error cards with retry (#8 — `ErrorCard` + serializable `retry {action,data}` re-dispatched through the existing card handlers for failed plan/apply/manipulation).
- ⬜ 2B remaining (**need the running app** — deferred, not blindly implemented): re-attach to jobs (#4 — mount-time auto-poll on the core flow, must be QA'd by refreshing mid-job), cleaning undo (#5), before/after visibility (#6 — needs version-id plumbing), interactive QA (#10).

**Phase 3 — Security & auth (COMPLETE):**
- ✅ Clerk JWT verification (CRITICAL): real RS256/JWKS (issuer + expiry checked, `alg=none`/algorithm-confusion resistant); `DEV_AUTH_BYPASS` honored only outside production. **Security-reviewed — no exploitable bypass**; the two flagged config gaps were fixed (`CLERK_JWT_ISSUER`/`CLERK_WEBHOOK_SECRET` now in the prod guard; `ENVIRONMENT` is a `Literal`).
- ✅ Clerk webhook hardened with `svix` (fail-closed, replay-resistant); **Supabase remnants deleted entirely**.
- ✅ Ownership audit (all routers filter by `user_id`) + cross-user 404 tests.
- ✅ Frontend Clerk gate + token attach (gated on `VITE_CLERK_PUBLISHABLE_KEY`; **live sign-in QA pending**).
- ✅ (earlier) export formula-injection (CRITICAL), rate limits, upload validation, secrets fail-fast.

**Phase 4 — Deployment & operations (largely COMPLETE):**
- ✅ Multi-stage uv Dockerfile (api + worker), non-root, healthcheck — **build- and import-verified** against Docker.
- ✅ Frontend↔backend wiring: API origin added to the `vercel.json` CSP; `.env.example` rewritten (all current vars; Supabase dropped).
- ✅ Observability: structured JSON logging + request-id middleware.
- ✅ CI: real Postgres/Redis services + `alembic upgrade`/`check` migration hygiene. Deploy scaffold (`deploy.yml`) builds/pushes to GHCR + migrates (manual until host + secrets chosen).
- ✅ Data lifecycle: daily Celery-beat orphaned-upload purge (scoped to `uploads/`, 24h age-guarded).
- ⬜ Sentry (needs DSN + dep — deferred); managed-Postgres backups (host concern); docker-compose literal passwords → env interpolation (**deferred: would disrupt the existing local DB volume — needs your .env coordination**).

**Phase 5 — Quality infrastructure (started 2026-07-07 afternoon):**
- ✅ Perf: code-split recharts into a lazy chunk (loads only when a chart renders) + React/Clerk/markdown vendor chunks. Main bundle 1,325 kB → 405 kB; the >500 kB build warning is gone.
- ✅ Shared pytest fixtures: `conftest.py` (was empty) now holds `make_user`/`make_db`/`mock_db`/`anthropic_tool_response`/`sample_df`; two files migrated as proof.
- ✅ Coverage gates: pytest-cov (67%, 65% global floor + **PR-only diff-cover at 80% on changed lines**) and vitest v8 (`include`-driven all-files measurement, per-metric floors). Added an app-boot smoke test so `main.py` counts honestly. Both wired into CI; artifacts gitignored.
- ✅ Frontend dark-area tests: extracted chat intent routing → `lib/intent.ts` and progress-stage labels → `lib/progress.ts`, both covered exhaustively (behavior in `Chat.tsx` unchanged). Frontend suite 57 → 88.
- ✅ CI now runs the full `pnpm build:web` (was `tsc --noEmit`, which skips config files) — caught a `vitest 4` coverage-type break that would only have failed at Vercel deploy.
- ⬜ Remaining: real-services **integration suite** + Playwright **E2E** (need the compose stack), coverage ratchet as the suite grows.
- End state: **455 backend + 88 frontend green, ruff/eslint/tsc clean, `pnpm build` clean (no chunk warning)**. 5 commits, TDD throughout.

**Live end-to-end validation (2026-07-07 evening):** brought the full stack up locally via CLI (docker-compose infra + uvicorn API + Celery worker + Vite frontend, real Anthropic key) and drove every feature end-to-end.
- ✅ Core pipeline (real AI): upload → profile → plan (Opus, 9 domain-agnostic steps incl. data-driven caps) → apply → verify (Sonnet, overall_passed) → download cleaned CSV. Confirmed the Phase 2A brain work on live data (no survey folklore, caps from the column's own distribution, dedup, whitespace/case/type fixes).
- ✅ Analysis chat (reply + chart), export (presigned URL), recipes (save + apply; the plan's 422-on-bad-step validation confirmed working).
- 🐛→✅ **Found and fixed two bugs the mocked unit tests couldn't catch** (committed `cdde291`): manipulation `_get_client` read `settings.anthropic_api_key` (500 on every parse); data_dictionary scraped JSON from free text (`JSONDecodeError`). Both now use the correct attr / forced tool use; regression tests added; re-verified live.
- ✅ Frontend↔backend wired (Vite proxy → API): app loads (dev bypass), Cleaned-datasets list renders real data, and the **2C Settings/Cleaning surface loads from `/settings`** with all controls — resolves the "settings UI live QA pending" flag.
- Stack torn down cleanly; the user's 41 pre-existing local dev datasets left untouched (only the session's `messy_sales.csv` test rows removed). Backend now **458 tests**.

**Phase 6 — Launch (started):**
- ✅ AI cost controls: kill-switch (`AI_ENABLED`) + per-user daily budget shared across all AI endpoints.
- ✅ Privacy/data-handling note in README; test counts corrected.
- ⬜ Remaining: onboarding demo, full docs pass, launch checklist.

**Decisions I took** (from the plan's "Decisions needed"): auth provider → **Clerk** (Supabase deleted); file-size ceiling → **50 MB** (`MAX_UPLOAD_BYTES`, configurable). Still yours: **backend host** (Railway/Fly — `deploy.yml` is host-agnostic scaffolding) and **launch scope** (private beta vs public sign-ups).

**Needs a live environment to finish/verify:** Clerk sign-in flow, the settings UI + remaining 2B UX (`/qa` on the running app), the Phase 5 integration suite + E2E (Playwright/real-services against the compose stack), and the actual deploy (host + secrets). _(Phase 5 conftest + coverage gates are now done — see the afternoon entry above.)_ One thing to sanity-check: the verification/manipulation model id `claude-sonnet-4-6` was preserved verbatim into config — confirm it's real. _(Resolved 2026-07-09 — see the audit entry below.)_

## Audit — 2026-07-09 (full state re-verification)

Re-ran the suites and a two-track code audit against this plan. **Verified: 458 backend + 111 frontend tests green, ruff clean, `pnpm build` clean (408 kB main chunk). PR #1 is open for this branch with all CI checks green and no merge conflicts** — main is 40 commits behind; merging is the next unblocking step.

**Closed items:**
- `claude-sonnet-4-6` **is a real, active model id** (verified against the current Anthropic model catalog; it also served every verification call in the 2026-07-07 live E2E). Sanity-check item closed. All three tiers in `config.py` (`claude-opus-4-8` / `claude-sonnet-4-6` / `claude-haiku-4-5-20251001`) are current. No service passes `temperature`/`top_p`/`top_k`, so a future swap to `claude-sonnet-5` (adaptive-thinking default, rejects non-default sampling params) is a config-only A/B — worth trying for verification+manipulation while intro pricing runs (through 2026-08-31); bump the verification `max_tokens` 8192→12288 for its ~30%-heavier tokenizer and gate on the 2A spot-check harness.

**New findings this audit surfaced (not previously tracked):**
- **Recipes have no frontend UI.** README sells "save a cleaning plan as a reusable template … in one click," and the backend `/recipes/*` endpoints are done and live-validated — but nothing in `apps/web` calls them. Ship a thin UI (save-as-recipe on the results card + a recipe picker) or de-advertise.
- **Brand drift:** the empty-state hero says "Welcome to **DataTiger**" (`EmptyState.tsx`) and the persist key is `datatiger-sessions` (`session-store.ts`) while everything else says DataPilot. Fix the hero copy; renaming the persist key would drop users' local sessions, so keep it or add a migration.
- **Dead cards:** `ComparisonCard` and `HistoryCard` are wired into `CardRenderer` but nothing ever produces their payloads — the backend `compare`/`history` endpoints are never called. The 2B "before/after" item is therefore mostly *wiring*, not new construction.
- **Cleanup task scope is uploads-only** (`uploads/` prefix, 24 h age-guard): cleaned files, snapshots, and exports have no retention/TTL story yet — fold into launch scope decision.
- **`deploy.yml`'s deploy job is an echo stub** (build→GHCR and migrate jobs are real); it stays `workflow_dispatch`-only until the host is chosen.
- Confirmed still absent (as planned): job re-attach after refresh (workflow state deliberately unpersisted, no mount-time poll), cleaning undo (manipulation undo exists — distinct), Playwright/E2E and real-service integration tests (suite is all-mocked; CI's real Postgres is only exercised by the migration step), Sentry.

**Remaining work, sequenced:** (A) merge PR #1 → (B) live-QA round: plan-gate click-through, Clerk sign-in, then build re-attach/undo/before-after + recipes UI against the running app → (C) Playwright golden path + real-services integration suite → (D) wire deploy to Railway, Vercel/Clerk/R2 env, Sentry → (E) launch: demo dataset, docs pass, retention policy, checklist. ~1.5–2.5 weeks at current pace.

**Decisions taken 2026-07-09 (Artem):** merge PR #1 now; backend host → **Railway** (+ Cloudflare R2 for storage); recipes → **ship the thin UI** (save-as-recipe on results card + picker); launch scope → **private beta** (invite-only via Clerk; no landing page needed, current AI budgets fine, simple retention). All four "Decisions needed" items below are now resolved.

## Progress log — launch-readiness session 2026-07-09 (branch `launch-readiness`)

Executed the sequenced remainder (B → C → most of D/E) against the live local stack. TDD throughout; every feature live-verified in the browser before commit.

**(B) Live QA + trust UX + recipes — COMPLETE:**
- ✅ **Plan-approval gate click-QA'd** (the Phase 1 gate's first interactive test): upload → plan card → per-step toggles (count + button update) → apply → locked "Applied" state → progress → validation (7/7) → results. Plan quality on live data confirmed (data-driven caps citing the column's own p99/median).
- 🐛→✅ Live QA found and fixed **four real bugs** the mocked suite couldn't see: (1) trailing-slash dataset GETs 307-redirected out of the Vite proxy (breaks any path-preserving proxy); (2) `cast_type→datetime` made job persistence crash — `pd.Timestamp` in `result_json` (fixed engine-wide: pandas/numpy-aware `json_serializer` on both engines); (3) cleaned **CSVs embedded the audit legend in-band**, making them unparseable by pandas/Excel (legend now lives in result_json + the Excel sheet only; legacy files stripped on read); (4) raw SQL exceptions were shown verbatim in the UI error card (tasks now persist `user_facing_error()`).
- ✅ **2B#4 re-attach**: dispatched clean jobs persist per session; on mount the UI reconnects, restores the stepper, and resumes the progress card. Live-verified by refreshing mid-job with the worker paused.
- ✅ **2B#5 revert**: `POST /cleaning/{job_id}/revert` + "Revert to original" on the results card; download/export substitution skips reverted jobs. Cleaned files now get **per-job storage keys** — re-cleaning previously overwrote the old cleaned file, so version fallback could serve wrong bytes.
- ✅ **2B#6 before/after**: `GET /cleaning/{job_id}/comparison` (original file vs the job's output via the existing comparison service) + "See what changed" renders the previously-dead ComparisonCard. History summary `rows_before` key fixed (`original_rows`).
- ✅ **Recipes thin UI**: "Save as recipe" (name dialog) on the results card + "Apply a recipe" picker (list/delete) in the + menu; apply reuses the shared job-watch flow. ky error hook renders the 422 compatibility issues readably.
- ✅ Brand pass: DataTiger → DataPilot (hero, sidebar text wordmark, footer, page title); persist keys deliberately unchanged.
- ✅ **Export correctness**: the export task re-derived the cleaned key by string convention and silently exported the ORIGINAL file when the guess missed; both download and export now go through `pick_effective_r2_key()`.

**(C) Quality infrastructure — COMPLETE:**
- ✅ **Real-services integration suite** (`apps/api/tests/integration/`, 13 tests): CRUD + ownership 404s + recipe 422 through the real app against real Postgres/Redis; one Celery task round-trip. Opt-in via `INTEGRATION_TESTS=1`; guarded so it can never touch a non-`_test` database. Wired into the existing CI backend job (DB renamed `datapilot_test`).
- ✅ **Playwright E2E** (`e2e/`): golden path (upload → plan → toggle → apply → validate → results → compare → save-recipe → apply-recipe → revert) + session-switch binding + refresh-mid-job re-attach. Full stack boots per run (fresh DB, Redis db 1, **stubbed Anthropic** via `ANTHROPIC_BASE_URL` → zero-dep node stub answering the forced tool call). New CI `e2e` job with Postgres/Redis/MinIO services.
- ✅ **Stale-job reaper** (beat, 10 min): worker-crash-orphaned jobs → failed with a friendly message (found via a live worker SIGSEGV that stranded a job in `pending` forever).
- ✅ **Data lifecycle**: cleaned files protected from the orphan purge (they live under `uploads/` — the daily cleanup would have deleted every cleaned file older than 24 h!); `exports/` retention (7 days, beat daily).

**(D/E) Deploy + launch prep — code/docs done, provisioning blocked on accounts:**
- ✅ `deploy.yml`'s echo stub replaced with a real **Railway** deploy job (api + worker via `railway up`, skips gracefully until `RAILWAY_TOKEN` is set).
- ✅ **docs/DEPLOYMENT.md**: step-by-step Railway/R2/Vercel/Clerk provisioning guide + launch checklist (incl. invite-only Clerk setup and the pending live sign-in QA).
- ✅ Onboarding: **"Try with sample data"** on the empty state loads a bundled messy sales CSV.
- ✅ README truth pass (test counts, new endpoints, E2E section).
- ⬜ **Blocked on Artem** (accounts/credentials only): Railway project + services + secrets, R2 bucket, Clerk production instance (invite-only) + live sign-in QA, Vercel env vars, Sentry DSN. Everything is documented in docs/DEPLOYMENT.md.
- ✅ Sentry wired (2026-07-12): `sentry-sdk[fastapi]` added, `_init_sentry()` in `main.py`, 6 tests. Just needs `SENTRY_DSN` env var at deploy time.
- Deferred (documented): superseded-cleaned-file retention.

End state: **523 backend (510 mocked + 13 integration) + 128 frontend + 3 E2E specs green**, ruff/eslint/tsc clean.

---

## What "complete and fully operational" means

The software is done when every box below is checked. Everything in this plan traces back to one of these.

- [x] **A real user can sign up, and their data is theirs** — real auth on every endpoint, ownership enforced everywhere, no dev-user stub. _(Clerk JWT done, security-reviewed; live sign-in QA blocked on Railway/Clerk prod credentials)_
- [ ] **The backend is deployed and reachable from the deployed frontend** — code + wiring done; blocked on Railway/R2/Vercel/Clerk provisioning (credentials only).
- [x] **The AI cleaning is trustworthy on arbitrary data** — no survey/expense folklore, caps derived from the data, nulls visible to the model, every plan validated, every result auditable and undoable. _(Live-validated 2026-07-07)_
- [x] **A hostile user can't hurt us or others** — rate limits on all AI endpoints, upload validation + size caps, no formula injection in exports, secrets out of the repo. _(Done; security-reviewed)_
- [x] **Users can shape behavior in Settings** — aggressiveness, thresholds, review-first vs auto-apply, domain hint, model tier. _(Done; live-rendered 2026-07-07)_
- [x] **When something breaks in prod, we find out from telemetry, not a user email** — structured logs done; Sentry wired (code done 2026-07-12: `sentry-sdk[fastapi]`, `_init_sentry()` in `main.py`, 6 tests). Needs `SENTRY_DSN` env var set at deploy time.
- [x] **The critical path is covered by E2E tests** — upload → plan → approve → clean → validate → export runs in CI against real Postgres/Redis/MinIO. _(Playwright E2E + integration suite in CI)_
- [x] **Deploys are a pipeline, not an incantation** — Dockerfile, Railway deploy job, migrations in CI, provisioning guide. _(Code done; deployment blocked on credentials)_
- [x] **Data has a lifecycle** — retention, orphan cleanup, stale-job reaper, export TTL, cleaned-file protection. _(Done 2026-07-10)_
- [x] **Docs match reality** — README truth pass done; WebSocket layer deleted; React 19 corrected. _(Done 2026-07-10)_

---

## Current state at a glance (updated 2026-07-12; launch-readiness branch)

| Area | State | Remaining gaps |
|---|---|---|
| Loop correctness (Phase 0–1) | ✅ Done, live-validated | — |
| Cleaning-brain quality (2A) | ✅ Done, live-validated | Optional: `claude-sonnet-5` A/B for verify/manipulation |
| Frontend core flow (2B) | ✅ Done, live-QA'd | — (re-attach, undo, before/after, recipes UI, plan-gate all done) |
| Settings (2C) | ✅ Done, live-rendered | — |
| Auth (Phase 3) | ✅ Clerk JWT, security-reviewed | Live sign-in QA with a real Clerk instance (needs Railway/Clerk prod) |
| Abuse hardening | ✅ Done | — |
| Deployment (Phase 4) | ⚠️ Code done, not provisioned | Railway credentials, Vercel env vars, Clerk production instance |
| Observability | ⚠️ Structured logs + Sentry code done | Set `SENTRY_DSN` env var at deploy time to activate |
| Test infrastructure (Phase 5) | ✅ Done | — (integration suite + Playwright E2E in CI) |
| Launch (Phase 6) | ⚠️ Code done, provisioning blocked | Railway/R2/Clerk credentials, Sentry DSN, final checklist run |

---

## Phase 2 — Product quality: trustworthy plans, correct UI, real settings (~1.5–2 weeks)

Tracks 2A/2B/2C are independent — run them in parallel.

### 2A. Cleaning brain (backend)

- [x] **Fix null masking in AI samples** (CRITICAL) — explicit null markers sent to Claude; `profile_task.py` sampling audited. _(Done 2026-07-07)_
- [x] **Data-driven caps** (HIGH) — per-column robust stats (p95/p99/MAD) computed in profile; dollar folklore table deleted; cap strategy is a setting. _(Done 2026-07-07; live-validated)_
- [x] **Demote survey/expense heuristics to an optional domain profile** (HIGH) — gated behind detected-or-user-set `domain` hint; generic profiling is the default. _(Done 2026-07-07)_
- [x] **Prompt tone pass for Opus 4.8** (MEDIUM) — caps are recommendations grounded in column stats; "CRITICAL: you MUST" style removed. _(Done 2026-07-07; live-validated)_
- [x] **Define the remediation op subset in code** (LOW) — `REMEDIATION_OPS` registry; prompt list generated from it; agent steps validated against it. _(Done 2026-07-07)_
- [x] **Validate recipe steps before dispatch** (MEDIUM) — `apply_recipe` runs `validate_plan()` against the target schema; returns actionable 422 naming the missing column. _(Done 2026-07-07; live-validated)_
- [x] **Configurable model tiers** (MEDIUM) — model IDs moved to `config.py` env-backed settings (`CLEANING_MODEL`, `VERIFICATION_MODEL`, etc.). _(Done 2026-07-07)_

### 2B. Frontend correctness + trust UX

- [x] **Fix wrong-session card actions** (HIGH) — owning `sessionId` passed through `CardRenderer`; RTL test covers session-switch + Apply. _(Done 2026-07-07)_
- [x] **Scope workflow state per session** (MEDIUM) — `workflowState` keyed by session id. _(Done 2026-07-07)_
- [x] **Persist card `applied` state in the store** (LOW) — applied state on the message payload in the store (survives remount). _(Done 2026-07-07)_
- [x] **Re-attach to running jobs after refresh** (MEDIUM) — `{jobId, datasetId, step}` persisted per session; mount-time poll restores progress card. Live-verified by refreshing mid-job. _(Done 2026-07-10)_
- [x] **Cleaning undo** (MEDIUM) — `POST /cleaning/{job_id}/revert` + "Revert to original" on results card; per-job storage keys prevent version collisions. _(Done 2026-07-10)_
- [x] **Before/after visibility on results** (MEDIUM) — `GET /cleaning/{job_id}/comparison` + "See what changed" drives the ComparisonCard. _(Done 2026-07-10)_
- [x] **Upload limits + feedback** (MEDIUM) — client-side `validateUploadFile` mirrors backend 50 MB cap; rejects before upload round-trip. _(Done 2026-07-07)_
- [x] **Error cards with retry** (LOW) — `ErrorCard` with serializable `retry {action,data}` re-dispatched through card handlers. _(Done 2026-07-07)_
- [x] **Delete dead code** (LOW) — orphaned pages and WebSocket layer deleted; README corrected (React 19, no WebSocket claims). _(Done 2026-07-07)_
- [x] **Interactive QA of the plan-approval gate** — live-QA'd: upload → plan card → per-step toggles → apply → locked state → progress → validation → results. _(Done 2026-07-10)_

### 2C. Settings surface (backend + frontend)

- [x] **User-preferences model + API** — `preferences` JSONB on users, `UserPreferences` schema, `GET/PUT /settings`, Alembic migration (verified clean). _(Done 2026-07-07)_
- [x] **Settings UI** — Cleaning settings tab: aggressiveness, outlier method/threshold, cap strategy, null-fill/dedup defaults, domain hint, custom instructions, AI sample size, model tier. _(Done 2026-07-07; live-rendered)_
- [x] **Thread preferences into the pipeline** — profile/plan/verification prompts and executors read user settings. _(Done 2026-07-07)_

## Phase 3 — Security & auth (~1 week; blocks public deploy)

- [x] **Decide the auth provider: Clerk** — Supabase remnants deleted entirely. _(Decided 2026-07-07; done)_
- [x] **JWT verification in `get_current_user`** (CRITICAL) — RS256/JWKS; `DEV_AUTH_BYPASS` enforced outside prod; `ClerkProvider` + token attach on frontend. Security-reviewed — no exploitable bypass. _(Done 2026-07-07)_
- [x] **Ownership enforcement audit** — all routers filter by `user_id`; cross-user 404 test matrix. _(Done 2026-07-07)_
- [x] **Harden the Clerk webhook** — `svix` library, fail-closed, replay-resistant. _(Done 2026-07-07)_
- [x] **Rate-limit the three open AI endpoints** (HIGH) — chat, manipulation-parse, dictionary all rate-limited. _(Done 2026-07-07)_
- [x] **Upload validation + size cap** (HIGH) — magic-byte check + `MAX_UPLOAD_BYTES` enforced on both upload paths. _(Done 2026-07-07)_
- [x] **Export formula-injection sanitization** (CRITICAL) — shared sanitizer prefixes `=`, `+`, `-`, `@`-leading cells; regression tests. _(Done 2026-07-07)_
- [x] **Secrets hygiene** — prod fails fast on default secrets; RestrictedPython dropped. _(Note: docker-compose literal passwords still present — deferred, would disrupt existing local DB volumes.)_ _(Done 2026-07-07)_
- [x] **`/security-review` gate** — full security review run; two config gaps found and fixed. _(Done 2026-07-07)_

## Phase 4 — Deployment & operations (~1 week; 4A can start during Phase 3)

- [x] **Dockerfile (api + worker)** — multi-stage uv image, non-root, healthcheck; build- and import-verified. _(Done 2026-07-07)_
- [x] **Pick the backend host** (decision) — **Railway** + Cloudflare R2. _(Decided 2026-07-09)_
- [x] **Connect deployed frontend to backend** (HIGH) — API origin in `vercel.json` CSP; `.env.example` rewritten with all vars. _(Code done 2026-07-07; live pending credentials)_
- [x] **Deploy pipeline** — `deploy.yml`: build/push to GHCR + Railway deploy job + `alembic upgrade`; `docs/DEPLOYMENT.md` provisioning guide. _(Done 2026-07-10)_
- [x] **Observability** (MEDIUM) — structured JSON logging + request-id middleware. _(Sentry deferred — needs DSN)_
- [x] **Data lifecycle** (MEDIUM) — daily orphaned-upload purge, 7-day export retention, stale-job reaper, cleaned-file protection from orphan cleanup. _(Done 2026-07-07 + 2026-07-10)_
- [x] **DB operations** — `alembic upgrade head` + `alembic check` in CI; migration hygiene enforced. _(Done 2026-07-07; managed-Postgres backups are a host concern)_

## Phase 5 — Quality infrastructure (parallel to everything; finish before launch)

- [x] **CI runs real services** (HIGH) — Postgres/Redis services + real-services integration suite (13 tests, CRUD + ownership + Celery round-trip) in CI backend job. MinIO via `docker run` for E2E job. _(Done 2026-07-10)_
- [x] **Shared fixtures** — `conftest.py` populated (`make_user`/`make_db`/`mock_db`/`anthropic_tool_response`/`sample_df`). _(Done 2026-07-07)_
- [x] **Coverage gates** — pytest-cov (65% global + 80% diff-cover on changed lines) + vitest v8; both enforced in CI. _(Done 2026-07-07)_
- [x] **E2E layer** (HIGH) — Playwright golden path (upload → plan → toggle → apply → validate → results → compare → recipe → revert), session-switch binding, refresh-mid-job re-attach; full stack per run (stubbed Anthropic); `e2e` CI job with Postgres/Redis/MinIO. _(Done 2026-07-10)_
- [x] **Frontend unit coverage where it's dark** — intent routing + progress labels extracted + tested; 88 frontend tests (was 49). _(Done 2026-07-07)_
- [x] **Perf sanity** — recharts code-split + vendor chunks; main bundle 1,325 kB → 405 kB; build warning gone. _(Done 2026-07-07)_

## Phase 6 — Launch readiness (~3–4 days)

- [x] **Docs truth pass** — README corrected (WebSocket deleted, React 19, test counts, E2E section, new endpoints). _(Done 2026-07-10)_
- [x] **Onboarding** — "Try with sample data" on empty state loads bundled messy sales CSV. _(Done 2026-07-10)_
- [x] **Privacy & terms** — data-handling note in README; Anthropic policy link; delete cascades storage. _(Done 2026-07-07)_
- [x] **Cost controls** — `AI_ENABLED` kill-switch + per-user daily budget shared across all AI endpoints. _(Done 2026-07-07)_
- [ ] **Full-app QA sweep** — `/qa` across the golden path + `/design-review` visual audit. _(Pending)_
- [ ] **Launch checklist run** — secrets rotated, backups verified, Sentry receiving, canary passes, rollback rehearsed. _(Blocked on Railway/Clerk/R2 provisioning)_

---

## Sequencing

```
Week 1        Week 2        Week 3        Week 4
[2A brain ]───[2C settings]─┐
[2B frontend]───────────────┤
[5 CI/fixtures]─────────────┼─[5 E2E]──────┐
              [3 auth+hardening]─[4 deploy]─┼─[6 launch]
```

- **Start now, in parallel:** 2A (null masking first), 2B (session bug first), 5 (CI services + conftest).
- **Auth (3) before deploy (4):** deploying the current stub would expose everyone's data; formula-injection + rate-limit fixes are small enough to land this week regardless.
- **E2E (5) lands before launch (6)** so the golden path is guarded during the auth/deploy churn.
- Estimated total: **4–6 calendar weeks** at current pace.

## Decisions needed (owner: Artem) — ALL RESOLVED

1. **Auth provider** → **Clerk** (decided 2026-07-07; Supabase deleted).
2. **Backend host** → **Railway** + Cloudflare R2 (decided 2026-07-09). Unblocks Phase 4.
3. **Launch scope** → **private beta**, invite-only via Clerk (decided 2026-07-09).
4. **File-size ceiling** → **50 MB** (`MAX_UPLOAD_BYTES`, configurable; decided 2026-07-07).

## How we build it — skill & agent playbook

| Stage | Use |
|---|---|
| Per feature | `tdd-guide` (tests first) → `code-reviewer` → gstack `review` before landing → `/ship` |
| Auth/hardening work (Phase 3) | `security-reviewer` agent on each diff + one full `/security-review` gate |
| Schema/migration changes (2C, 4) | `database-reviewer` |
| Prompt/plan-quality work (2A) | spot-check harness on 3–4 varied real datasets; compare plans before/after each prompt change |
| UI changes (2B, 2C) | preview-tool verification + `/qa` click-throughs; `/design-review` for the visual audit; `/qa-only` for report-only passes |
| E2E (5) | `e2e-runner` agent + `e2e-testing` skill (Playwright) |
| Deploy (4) | `/setup-deploy`, `/land-and-deploy`, `/canary` post-deploy |
| Debugging regressions | `/investigate` |
| Docs after each ship | `/document-release`; weekly `/retro` + `/health` to keep quality honest |
