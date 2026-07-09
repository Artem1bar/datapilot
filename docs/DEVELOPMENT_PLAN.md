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
- ⬜ **Blocked on Artem** (accounts/credentials only): Railway project + services + secrets, R2 bucket, Clerk production instance (invite-only) + live sign-in QA, Vercel env vars, Sentry DSN (then add sentry-sdk). Everything is documented in docs/DEPLOYMENT.md.
- Deferred (documented): superseded-cleaned-file retention; Sentry wiring until a DSN exists.

End state: **517 backend (504 mocked + 13 integration) + 128 frontend + 3 E2E specs green**, ruff/eslint/tsc clean.

---

## What "complete and fully operational" means

The software is done when every box below is checked. Everything in this plan traces back to one of these.

- [ ] **A real user can sign up, and their data is theirs** — real auth on every endpoint, ownership enforced everywhere, no dev-user stub.
- [ ] **The backend is deployed and reachable from the deployed frontend** — today the Vercel frontend has no backend to talk to (`VITE_API_URL` unset, no rewrite, CSP would block it); the live URL cannot clean a file end-to-end.
- [ ] **The AI cleaning is trustworthy on arbitrary data** — no survey/expense folklore, caps derived from the data, nulls visible to the model, every plan validated, every result auditable and undoable.
- [ ] **A hostile user can't hurt us or others** — rate limits on all AI endpoints, upload validation + size caps, no formula injection in exports, secrets out of the repo.
- [ ] **Users can shape behavior in Settings** — aggressiveness, thresholds, review-first vs auto-apply, domain hint, model tier.
- [ ] **When something breaks in prod, we find out from telemetry, not a user email** — structured logs, error tracking, job-failure visibility.
- [ ] **The critical path is covered by E2E tests** — upload → plan → approve → clean → validate → export runs in CI against real Postgres/Redis.
- [ ] **Deploys are a pipeline, not an incantation** — Dockerfile, one-command deploy, migrations applied automatically, rollback story.
- [ ] **Data has a lifecycle** — retention, orphan cleanup, delete actually deletes.
- [ ] **Docs match reality** — README features/API/stack tables true (today README still advertises the removed WebSocket layer).

---

## Current state at a glance (updated 2026-07-09; original 2026-07-07 table superseded)

| Area | State | Remaining gaps |
|---|---|---|
| Loop correctness (Phase 0–1) | ✅ Done, live-validated | — |
| Cleaning-brain quality (2A) | ✅ Done, live-validated | Optional: `claude-sonnet-5` A/B for verify/manipulation |
| Frontend core flow (2B) | ⚠️ Correct, trust UX incomplete | Job re-attach, cleaning undo, before/after wiring, recipes UI, plan-gate click-QA |
| Settings (2C) | ✅ Done, live-rendered | — |
| Auth (Phase 3) | ✅ Clerk JWT, security-reviewed | Live sign-in QA with a real Clerk instance |
| Abuse hardening | ✅ Done | — |
| Deployment (Phase 4) | ⚠️ Code-ready, not deployed | Host decision, deploy.yml stub → real, Vercel/CORS/Clerk env; live site still a shell |
| Observability | ⚠️ Logs only | Sentry (needs DSN), job-failure alerting |
| Test infrastructure (Phase 5) | ⚠️ Strong unit layer + gates | Real-services integration suite, Playwright E2E |
| Launch (Phase 6) | ⚠️ Started | Demo dataset, docs pass, retention policy, launch checklist, scope decision |

---

## Phase 2 — Product quality: trustworthy plans, correct UI, real settings (~1.5–2 weeks)

Tracks 2A/2B/2C are independent — run them in parallel.

### 2A. Cleaning brain (backend)

- [ ] **Fix null masking in AI samples** (CRITICAL) — `routers/cleaning.py:68` does `df.fillna("")` before sampling rows for Claude, so the model can't tell null from empty string and mis-plans null handling. Send explicit null markers (e.g. `<null>` or JSON `null`) in samples; audit `profile_task.py` sampling for the same pattern. _Accept: a dataset with mixed nulls/empties produces a plan that distinguishes them; regression test._
- [ ] **Data-driven caps** (HIGH) — `_cap_extreme_values` (`cleaning.py:654`) is purely param-driven; params come from hardcoded dollar folklore in `cleaning_system.txt:21–28` ("hotel: 50000") duplicated in `verification_system.txt:63–64`. Compute per-column robust stats (p75/p95/p99, MAD, max) in the profile, pass them to the model, and instruct it to derive caps from those — delete the dollar table. Cap strategy becomes a setting (off/auto/manual). _Accept: same column gets different caps on different datasets; no dollar literals left in prompts._
- [ ] **Demote survey/expense heuristics to an optional domain profile** (HIGH) — Qualtrics header detection (`profile_task.py:166–177`) and expense-column regexes (`profile_task.py:91–104`) run unconditionally. Gate them behind a detected-or-user-set `domain` hint; generic profiling is the default. _Accept: a non-survey CSV triggers zero survey-specific flags._
- [ ] **Prompt tone pass for Opus 4.8** (MEDIUM) — soften the "CRITICAL: you MUST add a cap step" style commands in `cleaning_system.txt` that force destructive ops on borderline data; caps become recommendations grounded in the supplied stats. Re-run plan-quality spot checks on 3–4 varied datasets.
- [ ] **Define the remediation op subset in code** (LOW) — verification agent's 16 allowed ops are hand-listed in `verification_system.txt:51–56` vs 22 in `_OPERATION_MAP`; the subset is intentional but unenforced. Add `REMEDIATION_OPS` to the registry, generate the prompt list from it, and validate agent steps against it. (Catalog duplication is otherwise resolved — keep it that way.)
- [ ] **Validate recipe steps before dispatch** (MEDIUM) — `recipes.py:134–196` `apply_recipe` skips `plan_validator` entirely; a recipe saved on one schema silently no-ops or fails mid-run on another. Run `validate_plan()` against the target dataset's schema and return actionable 422 errors. _Accept: applying a recipe with a missing column fails fast with the column named._
- [ ] **Configurable model tiers** (MEDIUM) — model IDs are hardcoded in 5 services (`cleaning.py:408`, `verification_agent.py:238`, `manipulation.py:94`, `analysis.py:104`, `data_dictionary.py:90`). Move to `config.py` env-backed settings (`CLEANING_MODEL`, `VERIFICATION_MODEL`, …); later surfaced per-user in Settings.

### 2B. Frontend correctness + trust UX

- [ ] **Fix wrong-session card actions** (HIGH) — `Chat.tsx:501–620` resolves `sessionId = activeSessionId` at click time; switch sessions while a plan card is pending and Apply targets the wrong session/dataset. Pass the owning `sessionId` through `CardRenderer` into every card action. _Accept: RTL test — render card in session A, switch to B, click Apply, action carries A._
- [ ] **Scope workflow state per session** (MEDIUM) — `session-store.ts:142–149` keeps one global `workflowState`; a second cleaning run overwrites the first. Key it by session (or job) id.
- [ ] **Persist card `applied` state in the store** (LOW) — `CleaningPlanCard.tsx:16` local `useState` resets on remount, making plans re-applyable. Mark applied on the message payload in the store.
- [ ] **Re-attach to running jobs after refresh** (MEDIUM) — workflow state is deliberately excluded from persistence (`session-store.ts:177–185`); a refresh mid-clean loses the progress card while the backend keeps working. Persist `{jobId, datasetId, step}` per session; on mount, poll `GET /jobs/{id}` and restore the progress card.
- [ ] **Cleaning undo** (MEDIUM) — manipulation has snapshot-based undo; cleaning doesn't (results card only offers Download/Analyze). Cleaning already writes a new dataset version — add "Revert to original" wired to the version history.
- [ ] **Before/after visibility on results** (MEDIUM) — `CleaningResultsCard` shows aggregates only; `ComparisonCard` already renders full diffs. Add a "See what changed" action on the results card that drives the existing comparison flow.
- [ ] **Upload limits + feedback** (MEDIUM) — client never states size/type limits and shows no upload progress (`AttachMenu.tsx:20`, `Chat.tsx:72–117`). Enforce the same max-size as the backend cap (Phase 3), reject oversize before upload, show staged status (uploading → profiling).
- [ ] **Error cards with retry** (LOW) — failed actions surface as plain chat text; add a error card with a retry action for plan/apply/export failures.
- [ ] **Delete dead code** (LOW) — six orphaned pages (`Landing/Dashboard/Upload/Clean/Analyze/Export.tsx`) are unrouted; `ws.py` + `test_ws.py` back a WebSocket layer the frontend no longer uses. Delete them (polling is the accepted mechanism at this scale) and update README, which still advertises "WebSocket-streamed job updates" and the `WS /ws/jobs/{job_id}` endpoint. Also: README says React 18, package.json says React 19.
- [ ] **Interactive QA of the plan-approval gate** — the Phase 1 gate (core-flow change) has never been click-tested. Run `/qa` against the local app: upload → plan card → toggle steps → apply → results, plus session-switching during a pending plan.

### 2C. Settings surface (backend + frontend)

- [ ] **User-preferences model + API** — `user_preferences` table (or JSONB on User), `GET/PUT /settings`, defaults in one place. Alembic migration (and fix the known drift: `ChatSession.updated_at` missing `onupdate` in the initial migration).
- [ ] **Settings UI** — beyond theme: cleaning aggressiveness (conservative/standard/aggressive), outlier method + threshold, cap strategy (off/auto/manual), null-fill & dedup defaults, domain hint, standing custom instructions, max remediation rounds, AI sample size, review-first vs auto-apply toggle, (admin) model tier per stage.
- [ ] **Thread preferences into the pipeline** — profile/plan/verification prompts and executors read the user's settings; plan cards show which settings shaped the plan.

## Phase 3 — Security & auth (~1 week; blocks public deploy)

- [ ] **Decide the auth provider: recommendation = Clerk** — the Clerk webhook handler already exists (`routers/auth.py`), `@clerk/clerk-react` is already a frontend dep, and vercel.json's CSP already whitelists Clerk; the Supabase side (`supabase_client.py`, `supabase/config.toml` with empty project id, unused `@supabase/supabase-js`) is vestigial. Pick one, delete the other's remnants entirely.
- [ ] **JWT verification in `get_current_user`** (CRITICAL) — `deps.py:20–41` returns a hardcoded dev user for every request. Verify the Clerk session JWT (JWKS), resolve/create the local user, keep a `DEV_AUTH_BYPASS` env flag for local dev that refuses to activate when `ENVIRONMENT=production`. Frontend: `ClerkProvider`, sign-in screen, `beforeRequest` hook on the ky client attaching the token (`lib/api.ts` is ready for it).
- [ ] **Ownership enforcement audit** — routers already filter by user consistently; re-verify every endpoint post-auth with a two-user test matrix (user B requests user A's dataset/job/recipe → 404).
- [ ] **Harden the Clerk webhook** — `auth.py:23–48` uses a simplified HMAC check without timestamp verification; use the `svix` library, fail closed when the secret is unset.
- [ ] **Rate-limit the three open AI endpoints** (HIGH) — `analysis.py:40` chat, `manipulation.py:47` parse, `dictionary.py:22` — the limiter service exists and is already applied to cleaning plan/apply and recipes; extend the same pattern.
- [ ] **Upload validation + size cap** (HIGH) — `validate_file_content()` exists (`utils/file_validation.py`) but the upload route (`datasets.py:64–111`) never calls it and enforces no size limit; the presigned `/confirm` path (`datasets.py:143–198`) accepts anything. Enforce magic-byte check + `MAX_UPLOAD_BYTES` on both paths (and validate after presigned upload lands).
- [ ] **Export formula-injection sanitization** (CRITICAL) — `services/export.py:10–43` writes raw `to_csv`/`to_excel`; a cell like `=cmd|...` executes in Excel. Prefix `=`, `+`, `-`, `@`-leading string cells with `'` (shared sanitizer for CSV + XLSX), regression tests with hostile fixtures.
- [ ] **Secrets hygiene** — docker-compose has literal Postgres/MinIO passwords (`docker-compose.yml:8–9,34–35`): move to env interpolation from untracked `.env`; rotate if the repo was ever public. `config.py` ships credentialed defaults — make prod fail fast if `ENVIRONMENT=production` and any secret is a known default. Remove the unused RestrictedPython dependency.
- [ ] **`/security-review` gate** — run the full skill over the auth + hardening diff before it lands.

## Phase 4 — Deployment & operations (~1 week; 4A can start during Phase 3)

- [ ] **Dockerfile (api + worker)** — one multi-stage image (uv-based), two commands (uvicorn / celery worker), healthcheck, non-root user, prod compose profile or platform config.
- [ ] **Pick the backend host** (decision) — needs long-running worker + Postgres + Redis + S3-compatible storage. Recommendation: **Railway or Fly.io** for api+worker+Postgres+Redis, **Cloudflare R2** for storage (config is already R2-shaped). Vercel stays frontend-only.
- [ ] **Connect deployed frontend to backend** (HIGH — the live site is a shell today) — set `VITE_API_URL` in Vercel env, add the API origin to the CSP `connect-src` (`vercel.json:22`), set backend `CORS_ORIGINS` to the Vercel domain, document `VITE_API_URL`/`VITE_CLERK_PUBLISHABLE_KEY` in `.env.example`. _Accept: upload→clean→export works on the production URL._
- [ ] **Deploy pipeline** — GitHub Actions: build/push image, run `alembic upgrade head`, deploy api+worker on main after tests pass; document rollback. `/setup-deploy` + `/land-and-deploy` skills can own this; `/canary` for post-deploy checks.
- [ ] **Observability** (MEDIUM) — structured JSON logging with request-id middleware; Sentry (or equivalent) for API + Celery with release tagging; alert on job-failure rate. Track per-job Anthropic token spend in `result_json` → simple cost dashboard/log line.
- [ ] **Data lifecycle** (MEDIUM) — periodic Celery beat task: purge orphaned R2 objects (task died between object write and job record), optional retention policy (e.g. datasets older than N days for free tier), TTL for stale export files.
- [ ] **DB operations** — backups on the managed Postgres, `alembic upgrade` in the deploy path, migration-hygiene check in CI (autogenerate diff must be empty; catches drift like the `updated_at` case).

## Phase 5 — Quality infrastructure (parallel to everything; finish before launch)

- [ ] **CI runs real services** (HIGH) — `test.yml` sets `DATABASE_URL`/`REDIS_URL` but starts no containers; nothing exercises real Postgres/Redis. Add `services:` blocks + a small integration suite (real DB round-trips for datasets/jobs/recipes CRUD, one full Celery task run with eager mode against real Redis).
- [ ] **Shared fixtures** — `tests/conftest.py` is empty; every file hand-rolls mocks. Centralize app/client/DB/Anthropic-mock fixtures to cut duplication before the test suite doubles again.
- [ ] **Coverage gates** — pytest-cov + vitest coverage with an 80% line on changed code (enforced in CI, not aspirational).
- [ ] **E2E layer** (HIGH) — Playwright: upload → plan → toggle steps → apply → progress → results → export; a second spec for session switching + refresh-mid-job re-attach; run against compose stack in CI (mock Anthropic via a recorded-response shim). The `e2e-runner` agent + `e2e-testing` skill own this.
- [ ] **Frontend unit coverage where it's dark** — Chat intent routing, `handleCardAction`, job polling hooks; component tests beyond `CleaningPlanCard`.
- [ ] **Perf sanity** — code-split the chart panel (build warns >500 kB chunks); document the practical file-size ceiling (full-DataFrame-in-memory per task, re-parsed per stage — fine at survey scale, revisit Parquet working-copy caching only if real usage demands it).

## Phase 6 — Launch readiness (~3–4 days)

- [ ] **Docs truth pass** — README features/API/stack corrected (WebSocket claims out, React version, auth setup, deploy guide); `/document-release` after each ship.
- [ ] **Onboarding** — empty-state demo dataset ("try with sample data"), first-run hints; a real landing page only if public sign-ups are the goal.
- [ ] **Privacy & terms** — uploaded data goes to Claude: state it, link Anthropic's data policy, delete-my-data flow (delete already cascades storage — verify and say so).
- [ ] **Cost controls** — per-user daily AI budget (token or call based) on top of rate limits; kill-switch env flag for AI endpoints.
- [ ] **Full-app QA sweep** — `/qa` across the golden path + `/design-review` visual audit on the four core screens; fix what falls out.
- [ ] **Launch checklist run** — secrets rotated, backups verified, Sentry receiving, canary passes, rollback rehearsed once.

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
