# Changelog

All notable changes to DataPilot are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

- Backend deployment pending (Railway + Clerk + R2 provisioning required — see `docs/DEPLOYMENT.md`).

### Code export: Python and R scripts that reproduce every answer (Phase 5)

The pipeline's claim is that every reported number was computed from the uploaded
file by deterministic code, not produced by a model. Code export makes that
claim checkable: for any validated analysis spec it renders the equivalent
Python (scipy/pandas/numpy) or R (dplyr/tidyr/base stats) — imports, a load
line the reader edits, the filter, then one commented block per operation.

An operation with no emitter is never silently dropped; it becomes a commented
placeholder carrying the parameters it was given. An export that omits a step
would read as a complete reproduction, and would not be one.

Tests execute the generated Python against the same dataframe and compare it
with the pipeline's own output, so faithfulness is a test condition, not an
assertion.

Two dialects (Python, R) cover operations in Tiers 1–4. Tier 5 (time series)
and Tier 6 (weighted survey) register their emitters from companion dialect
modules imported automatically when the façade is loaded.

### Time series: trends, seasonality, stationarity, anomalies, and forecasts (Phase 6)

Where tier 3 asks whether two groups differ, time series asks whether a series
trends, repeats, remembers its own past, and whether one series precedes
another. All operations start by converting the timestamp column to a regular
daily/weekly/monthly/quarterly/annual index, reporting any gaps filled.

- `trend_seasonality` — STL decomposition into trend, seasonal, and remainder
  components; classifies whether the trend is up, down, or flat and whether
  seasonality is strong or absent
- `autocorrelation` — ACF and PACF at user-specified lags; reports which lags
  are significant and what that implies for ARIMA order selection
- `stationarity` — ADF, KPSS, and (optionally) Phillips-Perron tests; reports
  the agreed verdict and the number of differences required to achieve it
- `forecast` — ARIMA(p,d,q) or auto-selected via AIC; every forecast point
  carries its prediction interval; point forecasts without intervals are not
  shipped; the notes state that the interval assumes the fitted model is correct
  and widens with horizon
- `granger_causality` — predictive precedence test; every result carries a note
  saying so, whatever the p-value, because the name has been misread since Granger
  introduced it

Interpolated periods are counted, named in the notes, and counted against the
regular-spacing assumption, which the narrator is required to surface.

### Regression analysis: OLS, GLM families, quantile regression (Phase 4)

Statistical modelling where the question is "how much does X predict Y, and
for whom?" rather than "do these groups differ?"

- `ols` — ordinary least squares with heteroskedasticity-robust (HC3) standard
  errors by default, plus the option of classic homoskedastic SEs for
  comparison; reports coefficients, CIs, p-values (BH-adjusted), R², and F
- `logistic` — binary logistic regression with odds ratios and marginal effects;
  McFadden's R² alongside the standard pseudo-R²
- `quantile` — estimates conditional quantiles (default: 0.25, 0.50, 0.75)
  without any distributional assumption; useful where conditional means hide the
  story for the tails
- Every model reports the same coefficient table format so the frontend can
  render them uniformly in the AnalysisCoefficientTable card

statsmodels>=0.14.4 added for GLM families, robust standard errors, and
quantile regression.

### Survey and weighted analysis: estimates that account for sampling design (Phase 3)

When a dataset is a survey or uses sampling weights, unweighted means and
proportions are wrong in a measurable way. This tier applies the weights.

- `weighted_mean` — mean, SE, and 95% CI under the specified weight column;
  reports effective n (= (Σw)²/Σw² — lower than n when a few rows dominate)
- `weighted_proportion` — Wilson interval applied to the weighted count
- `subgroup_estimate` — one row per subgroup, with weighted mean and effective n
  for each; supports both mean and proportion outcomes
- `design_effect` — the ratio of the variance under the design to the variance
  of a simple random sample of the same size; DEFF > 1 means the weights are
  inflating uncertainty
- `rao_scott_chi_square` — the design-corrected chi-square for a weighted
  two-way table, with Cramér's V computed from the design-adjusted statistic

Survey variance uses the linearisation (Taylor series) estimator: fast, no
resampling required, exact for proportions under binomial and for means under
large n.

### Inferential statistics, assumption checks, and provenance (Phase 2)

Phase 1 made the numbers real. Phase 2 makes them defensible: analysis can now
test whether a difference is distinguishable from chance, and every answer
carries the record of how it was produced.

Eight inferential operations join the eleven descriptive ones:

- `ttest` — one-sample, independent (Welch by default), or paired
- `anova` — one-way, with Tukey HSD pairwise comparisons
- `kruskal`, `mannwhitney`, `wilcoxon` — rank-based equivalents that assume no
  normality, for skewed, ordinal, or small-n data
- `chi_square` — independence (Cramér's V, plus an exact Fisher result on 2x2
  tables) or goodness of fit against an even split
- `proportion_test` — one- and two-sample, with Wilson and Newcombe intervals
- `normality_test` — the check behind choosing a t-test over a rank test

**Every test reports four things beside its statistic**: an effect size with
Cohen's conventional magnitude label, a confidence interval, explicit assumption
checks, and n. A p-value alone invites the two commonest mistakes in applied
statistics — reading significance as importance, and running a test whose
assumptions the data violate.

**Assumption checks are three-valued.** `true`, `false`, and `null` for "could
not be evaluated", which is not the same as passing. The narrator prompt now
requires a failed check to appear in the same breath as the finding it
undermines, rather than as a closing caveat.

**Operations refuse rather than degrade.** An independent t-test over three
groups raises and names ANOVA instead of silently comparing the first two. The
validator learned the actual values of low-cardinality columns, so a filter on
`"Weest"` or a `success_value` of `"Yes"` where the data says `"yes"` is
rejected with the real spellings — a rejection the model can act on, instead of
an empty result it cannot explain.

**Multiple comparisons.** P-values across the tests in one answer are adjusted by
Benjamini-Hochberg, and the narrator treats the adjusted value as the one that
decides significance.

**Provenance.** Every computed answer now returns a record of what ran — the
operations and their parameters, n and n_excluded per operation, every
assumption check, and the exact pandas/numpy/scipy/Python versions — rendered as
a markdown methods note. Nothing in that path calls a model: a methods note
written by the thing whose trustworthiness it attests to would be worth nothing.
It surfaces in the chat as a collapsible **Methods** card with a copy button.
The field is additive (`provenance`, null on a refusal), so existing clients are
unaffected.

New modules, split so each stays readable: `analysis_stats.py` (effect sizes,
intervals, assumption checks as pure array functions), `analysis_prep.py` (group
splitting shared by every test), `analysis_inference.py` (mean and rank
comparisons), `analysis_categorical.py` (counts and proportions),
`analysis_provenance.py` (the record and its rendering), `analysis_result.py`
(the shared result type). No new dependencies.

Two defects found and fixed while verifying:

- P-values below the rounding precision serialized as `0.0`. A methods note
  reading `p = 0` claims certainty no test can support. Values below 1e-4 now
  keep significant figures rather than decimal places.
- Dropped incomplete pairs were reported as a *failed* assumption, which under
  the narrator's rules would have had routine missingness described as
  undermining the result. It is now "not evaluated", with the count and the
  condition under which it would actually matter.

Verified end-to-end against a 600-row dataset: t/F/z/chi-square statistics,
degrees of freedom, Cohen's d, eta and omega squared, Cramér's V, Cohen's h,
both CI bounds, and every group mean and proportion matched statistics computed
independently from the raw arrays. `z²` equalled the uncorrected chi-square on
the same table, as it must.

Backend tests: 751 → 875 (89% coverage across the analysis modules). Frontend:
128 → 139.

### Analysis now computes instead of generating (Phase 1)

Previously `analyze_data()` sent the profile and 20 sample rows to a model and
asked it to produce the answer *and the chart values*, so every rendered figure
was generated rather than measured. Analysis now follows the same trust model as
cleaning: the model proposes a validated plan, deterministic code executes it,
and the model explains the results it is given.

- `app/services/analysis_spec.py` — operation whitelist and validator. A spec is
  checked against the registry and the dataframe's real columns and dtypes before
  anything runs; an unknown op, a hallucinated column, or a numeric aggregation
  over a text column is rejected, not coerced. All problems are reported at once
  so regeneration takes one round trip. A `refusal` is a valid terminal state.
- `app/services/analysis_executor.py` — deterministic execution in pandas/scipy
  over the **full** dataframe. Every result carries `n`, `n_excluded`, and notes,
  so the narrator can say "excluding 38 rows with missing revenue" rather than
  reporting a mean over an unstated denominator.
- Eleven operations: `describe`, `groupby_aggregate`, `value_counts`, `crosstab`
  (chi-square), `histogram`, `top_n`, `pivot`, `resample`, `correlation_matrix`
  (pairwise p-values), `scatter_with_fit` (OLS slope/R²/p), `group_comparison`
  (95% CIs plus Welch's t-test or one-way ANOVA).
- Two prompts replace one: `analysis_plan.txt` (emit a spec, never a number) and
  `analysis_narrate.txt` (explain computed results; introducing an unsupplied
  figure is forbidden, as is claiming causation).
- The planner's capability list is generated from the `OPERATIONS` registry, so
  the prompt cannot drift from what the validator accepts.
- The API response contract (`answer`, `charts`, `tables`) is unchanged — the
  frontend needed no rewrite.
- Adds `scipy>=1.14.0`.

Verified end-to-end against a 480-row dataset with independently computed ground
truth: regional totals, segment means, both CI bounds, sample sizes, and the
t-statistic matched exactly, and an unanswerable question was refused rather
than answered.

### Fixed
- `build_chart` plotted result column 1 unconditionally, so a `group_comparison`
  chart titled "average revenue" rendered group *sizes* — its columns are
  `[group, count, mean, ...]`. Charts now resolve the y column from the spec's
  optional `y`, then a per-operation default, then column 1.
- Non-finite statistics (a t-test over zero-variance groups returns NaN) are
  emitted as `null`. NaN is not valid JSON, so the API had been able to produce
  a response no JSON parser accepts.
- `_load_analysis_frame` tested for dtype `"object"` to find text columns, which
  matches nothing on pandas 3 (it reports `"str"`). Date parsing silently never
  ran. It now tests for what a column is *not* — neither datetime nor numeric.

### Tests
- `test_analysis_spec.py`, `test_analysis_executor.py` — validator gate and
  execution correctness, asserted against hand-computed values rather than
  "a number came back".
- `test_analysis.py` rewritten for the new architecture.
- Backend total: 678 → 751 tests.

### Changed
- Model tiers moved to the Claude 5 family. Cleaning, verification, and manipulation
  all run on `claude-opus-5` (they mutate user data, so they get the strongest model);
  analysis runs on `claude-sonnet-5` for chat latency — set `ANALYSIS_MODEL=claude-opus-5`
  to trade latency for depth. `DICTIONARY_MODEL` stays on Haiku 4.5.
- `test_verification_agent.py` asserts the model against `settings.VERIFICATION_MODEL`
  instead of a hardcoded id, so model bumps no longer break the test.

### Added
- `LLM_BACKEND` setting selecting how model calls are dispatched. `"api"` (default)
  uses the Anthropic SDK billed to `ANTHROPIC_API_KEY`; `"cli"` subprocesses the local
  `claude` binary so usage bills the operator's Claude subscription.
- `app/services/llm_cli.py` — the CLI backend. Strips the coding-agent harness
  (`--system-prompt`, `--setting-sources ""`, `--strict-mcp-config`, `--tools ""`),
  which measured ~50k → ~600 tokens of preamble on a one-word reply; removes
  `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` from the child environment so a stray
  key cannot silently redirect billing to the API; sends prompts over stdin.
- `structured_output.complete_text()` — text-completion twin of `request_tool_call()`,
  so both backends sit behind one helper and services never branch on the backend.
- Production refuses to boot with `LLM_BACKEND != "api"` (`production_secret_problems`):
  the CLI backend drives one person's subscription and cannot serve real users.
- `test_llm_cli_backend.py` — 27 tests covering argv construction, env stripping,
  failure modes, message flattening, JSON extraction, and backend dispatch.
  Backend total: 651 → 678 tests.
- `docs/ANALYSIS_STATISTICS_SCOPE.md` — scope for replacing the LLM-generated
  analysis path with plan → validate → execute → narrate over real computation.

### Known limitation
- Under `LLM_BACKEND="cli"` there is no forced tool use, so structured output is
  parsed out of the reply with a retry instead of guaranteed by the API. This is
  strictly weaker than the API path and is one reason the CLI backend is for
  closed testing only.

## [0.5.2] — 2026-08-18

### Fixed
- Suppress `RuntimeWarning: coroutine ... was never awaited` in `test_exports_router_http.py` by overriding `db.add` with a synchronous `MagicMock` — `session.add()` is synchronous in SQLAlchemy async sessions, so `AsyncMock` was incorrect here.

---

## [0.5.1] — 2026-08-17

### Tests
- `test_profile_task_helpers.py` — 32 new unit tests for pure helper functions: `_to_python` (numpy/pandas→Python type coercion), `_compute_profile` (stats, percentiles, JSON safety, quality flags), `generate_smart_suggestions` (drop/type/PII detection), `detect_quality_issues` edge cases (dirty column names, empty columns, number words, extreme outliers).
- Backend total: 619 → 651 tests.

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
