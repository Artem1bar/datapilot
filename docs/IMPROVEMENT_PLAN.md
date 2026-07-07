# DataPilot Improvement Plan

_Audit date: 2026-07-06 (commit 76b0632). Goal: polish DataPilot into a reliable, high-quality data-cleaning tool. Verified baseline: 333 backend + 43 frontend tests green, ruff/eslint clean, `pnpm build` broken (tsc), real-time progress layer disconnected end-to-end._

> **Status 2026-07-07:** Phases 0–1 below are complete and committed. Phases 2–3 are superseded by the full completion roadmap in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) (re-audited 2026-07-07); this file remains as the original audit trail.

**Architecture verdict: keep the shape, tighten it.** FastAPI + Celery + Postgres + S3 with a fixed, auditable operation vocabulary and a verify-and-remediate loop is the right design for trustworthy cleaning. Do not move to free-form code generation as the primary path. Consolidate duplicates (two op registries, five `_read_dataframe` copies, decorative WebSocket layer, dual half-wired auth).

---

## Phase 0 — Stop the bleeding (~1 day)

- [x] **Fix broken frontend build**: `vite.config.ts` missing Vitest type augmentation; stale fixture in `session-store.test.ts:218`. `pnpm build` must pass.
- [x] **pandas 3.0 fixes**: `fillna(method=)` crash in `manipulation_executor.py` (use `.ffill()`/`.bfill()`); `fillna(None)` no-op in `datasets.py` preview leaks `NaN` into JSON (use `.astype(object).where(notna, None)`).
- [x] **`_drop_rows` audit-key mismatch** (`cleaning.py`): writes `rule`/`row_id` instead of `operation`/`row`, so `_compute_audit_completeness` never credits the qualtrics-header fix → depressed score → wasted verification-agent rounds.
- [x] **`cast_type` → str null handling**: verified pandas 3.0's `astype(str)` already preserves NA (the corruption only existed on pandas < 3); regression tests added in both executors to lock the behavior in.
- [x] **Celery engine leak**: fresh `create_engine()` per task invocation, never disposed — cache one sync engine per worker process.
- [x] **Event-loop blocking**: wrap synchronous `_read_dataframe` calls in `asyncio.to_thread` in `datasets.py` (schema/validate/preview/compare).
- [x] **Dead delete button** in CleanedDatasets: add `DELETE /datasets/{id}` (DB row + stored objects) and wire the button with confirm.

## Phase 1 — Make the loops actually work (~1 week)

- [x] **Plan-time validation + regeneration loop** (there is none today): strict step validator (operation ∈ registry, column exists, params schema per op); on invalid plan, regenerate once feeding the specific errors back to Claude; fail loudly with details after that.
- [x] **Structured outputs**: plan generation and the verification agent no longer scrape JSON from free text — both force a single tool call (`tool_choice={"type":"tool"}`) via a shared `structured_output.request_tool_call` helper, so the SDK returns an already-parsed dict. (Forced tool use, not `messages.parse`/`output_config.format`: Sonnet 4.6 — the verification agent's model — doesn't support `output_config.format`, and the freeform `params` object can't be a strict schema.) Plan steps now carry a real per-step `rationale` + `confidence`; frontend surfaces both and no longer fakes `0.9`. Removed the dead `_extract_json_from_response`.
- [x] **Remediation-loop convergence** (`cleaning_task.py`): agent remediation steps are validated pre-execution (done earlier); a convergence guard (`_remediation_stalled`) now stops the loop when a round fails to shrink the remaining flags instead of re-burning a verification-agent call, and records the survivors as `unresolvable_flags` in the report (surfaced in the results card); the verification agent's output cap was raised 4096→8192; the persisted report always reflects the post-remediation state.
- [x] **Honest progress**: persist `progress` to the Job row at each pipeline stage so polling shows real progress (today DB progress is only written at 5% and 100%); frontend progress card reads it. Decide fate of the WS layer separately (wire it properly or delete it — today it is triple-disconnected: no token sent, no `/ws` proxy, hook unused).
- [x] **Retry semantics**: only mark a job `failed` when Celery retries are exhausted; don't retry deterministic errors (bad file, invalid plan); no more failed→completed status flip-flop.
- [x] **Plan approval gate in chat**: `runCleaningWorkflow` now stops after the plan card instead of auto-applying; the plan card (`CleaningPlanCard`) has per-step toggle checkboxes + an explicit "Apply N steps" button that dispatches an `apply_cleaning` action → the extracted `applyCleaningSteps()` runs the clean job. Step pass/fail is surfaced in the validation card and remediation/unresolvable-flags in the results card. (NB: whether chat should default to review-first vs auto-apply is revisited as a Phase 2 setting; this ships review-first.)

## Phase 2 — Better plans + real settings (~1–2 weeks)

- [ ] **Generalize the cleaning brain**: survey/Qualtrics heuristics become one optional domain profile, not the hardcoded default (`profile_task.detect_quality_issues`, `cleaning_system.txt`).
- [ ] **Data-driven caps**: replace fixed dollar ceilings ("hotel: 50000") with robust percentile-based caps computed from the actual column; caps become suggestions the model tunes, never invents from domain folklore.
- [ ] **Single-source op catalog**: generate the operation list + param schemas in all prompts from the registry (three hand-written copies currently drift; the verification agent can't even propose some existing ops).
- [ ] **Prompt tune for Opus 4.8**: de-prescribe CRITICAL/MUST language (current prompt over-triggers destructive caps); stop masking nulls as `""` in samples sent to the model.
- [ ] **Settings surface** (backend `Settings` + user-preferences table + UI): cleaning aggressiveness, outlier method/threshold, cap strategy (off/auto/manual), null-fill & dedup defaults, domain hint, standing custom instructions, max remediation rounds, AI sample size, per-stage model tier, review-first vs auto-apply. (Also fix the Settings page "System" theme bug.)
- [ ] **Trust UX**: before/after diff on results card; one-click undo for cleaning (reuse snapshot mechanism); persist sessions/workflow server-side (refresh currently wipes mid-job state); real error surfaces with retry actions.
- [ ] **Consolidation**: one operation registry behind an `Operation` protocol (merge cleaning's 22 + manipulation's 13); one `_read_dataframe`; dataset lineage columns (`parent_dataset_id`, `source_job_id`, stored `cleaned_r2_key`); cap audit log persisted in `result_json` (full legend only in exported file); Parquet working copy after first parse.

## Phase 3 — Ship-readiness (before real users)

- [ ] **Real auth**: pick ONE provider (Clerk or Supabase); JWT verification in `get_current_user` (today: hardcoded dev user for every request); job-ownership check on the WS route; `svix`-verified webhook that fails closed; delete the unused half of auth/storage seams and the unused RestrictedPython dependency.
- [ ] **Abuse hardening**: rate limits on analysis/manipulation/dictionary AI endpoints; `validate_file_content` at upload time + hard size cap; CSV/Excel formula-injection sanitization on export.
- [ ] **Deployment**: Dockerfile + api/worker production profile, env-var credentials (compose file has hardcoded ones), managed Postgres/Redis/object-store targets.
- [ ] **Optional/later**: sandboxed, reviewed code-gen *fallback* for long-tail transforms (never replacing the audited registry); polars in the executor if file sizes demand it; E2E test layer (Playwright) for the upload→clean→export flow.

---

## Key defects found in the audit (for traceability)

| # | Severity | Finding | Where |
|---|---|---|---|
| 1 | CRITICAL | `pnpm build` broken (2 tsc errors) | `apps/web/vite.config.ts:22`, `src/stores/session-store.test.ts:218` |
| 2 | CRITICAL | No auth — every request resolves to one hardcoded dev user | `apps/api/app/deps.py:20-41` |
| 3 | CRITICAL | No plan regeneration/validation; hallucinated steps fail silently mid-run | `apps/api/app/services/cleaning.py:89,346,373` |
| 4 | CRITICAL | `fillna(method=)` crashes on pandas 3.0.1 (ffill/bfill manipulations broken) | `apps/api/app/services/manipulation_executor.py:252` |
| 5 | HIGH | Real-time progress triple-disconnected; DB progress only 5%→100%; WS hook unused | `ws.py`, `use-job-socket.ts`, `cleaning_task.py` |
| 6 | HIGH | Remediation loop: audit-key mismatch depresses completeness, wastes agent rounds | `cleaning.py:589` vs `verification.py:444` |
| 7 | HIGH | Jobs marked failed *before* Celery retries (status flip-flop, duplicate LLM spend) | `cleaning_task.py:448`, `profile_task.py:508`, `export_task.py:177` |
| 8 | HIGH | Chat flow auto-applies AI plan with no user approval gate | `apps/web/src/pages/Chat.tsx:357-383` |
| 9 | HIGH | Preview endpoint leaks `NaN` (invalid JSON) for null numeric cells | `apps/api/app/routers/datasets.py:332` |
| 10 | HIGH | Upload path never calls content validation; no size cap; AI endpoints unratelimited; CSV formula injection on export | `datasets.py`, `export.py`, `analysis.py`, `manipulation.py`, `dictionary.py` |
| 11 | HIGH | Cleaning brain overfit to Qualtrics/expense domain; hardcoded caps destructive elsewhere | `profile_task.py:92-105`, `prompts/cleaning_system.txt:20-29` |
| 12 | MEDIUM | Excel audit comments misalign after row-dropping steps; `free_to_zero` matches "Freelance"; abs-z outlier flagging nulls the 0s `free_to_zero` created (cast_type→str null corruption turned out to be fixed by pandas 3 itself — regression tests added) | `cleaning.py`, `cleaning_task.py:114` |
| 13 | MEDIUM | Celery tasks leak a fresh engine per run; 4 endpoints parse files on the event loop | `profile_task.py:47`, `datasets.py:218+` |
| 14 | MEDIUM | Sessions/workflow state localStorage-only (refresh wipes mid-job UI); export silent failure; dead delete button; Settings = theme only (with a "System" bug) | `apps/web/src/...` |

_Positive findings worth preserving: no code-execution surface (closed dispatch tables — keep it that way); consistent ownership filtering pattern in routers; well-designed sliding-window rate limiter; safe markdown rendering; CORS guard at startup; correctly configured Celery (acks_late, prefetch 1)._
