# Scope: real statistical analysis

_Drafted 2026-08-26. **Phase 1 shipped 2026-08-26** — Tier 1 + Tier 2 and the
plan → validate → execute → narrate architecture. **Phase 2 shipped 2026-08-27**
— Tier 3, assumption checks, effect sizes, and provenance. **Phases 3 and 4
shipped 2026-08-27** — Tier 4 regression, Tier 5 time series, Tier 6 survey
estimation, code export in Python and R, a planner dataset briefing, and ten
fixes from an independent audit of the Tier 1–3 code. Thirty-three operations._

## The problem

`analyze_data()` does not analyze data. It sends `profile_json` plus the first 20
sample rows to a model and asks the model to write the answer *and the chart
numbers*. From `app/prompts/analysis_system.txt`:

> Use the profile statistics to compute realistic aggregated values for charts

Nothing executes. The model never sees the full dataset, and every figure it
renders is generated from summary statistics rather than measured. For a chart of
"revenue by region" on a 40,000-row file, the model has seen 20 rows and a set of
column-level means — the bars are plausible fiction.

Three consequences, in order of severity:

1. **Fabricated values presented as measurements.** No caveat, no confidence
   marker. This is worse than refusing to answer.
2. **No inferential capability at all.** Dependencies are pandas + numpy only:
   no scipy, no statsmodels, no scikit-learn. There is no test, no model, no
   standard error anywhere in the codebase.
3. **Profiling is univariate.** `_compute_profile` covers mean/std/median/p95/
   p99/MAD per column. Nothing bivariate — no correlation, no cross-tabulation.

The cleaning pipeline already solved this exact problem correctly, and analysis
just never got the same treatment.

## The architecture: reuse what cleaning already gets right

Cleaning never lets the model touch data. It has the model emit a **plan**, that
plan is validated against an operation whitelist (`REMEDIATION_OPS`), and pandas
executes it deterministically with a per-cell audit log. The model chooses; code
computes.

Apply the same shape to analysis:

```
question + profile
      │
      ▼
 [1] PLAN      LLM → AnalysisSpec (structured, no numbers)
      │
      ▼
 [2] VALIDATE  spec vs. operation whitelist + real columns/dtypes
      │
      ▼
 [3] EXECUTE   pandas / scipy / statsmodels over the FULL dataframe
      │
      ▼
 [4] NARRATE   LLM → prose, given the computed results
```

The trust inversion is the whole point: **the model decides what to compute and
explains what it means, but never supplies a value.** Charts render from step 3's
output. Step 4 receives real numbers and interprets them.

Step 2 must also be able to refuse — "this question cannot be answered from this
data" is a valid terminal state (asking for a causal effect with no
identification strategy, a t-test at n=3, a trend with no date column).

### Why not let the model write and run code?

A sandboxed code path is more flexible and strictly more dangerous: arbitrary
execution against user data, and no way to validate intent before it runs. The
declarative whitelist keeps the property that makes cleaning trustworthy — you
can read the spec and know what will happen before it happens. Revisit only if
the whitelist demonstrably cannot express what users ask for.

## Operation whitelist, by tier

Each tier is independently shippable. Tier 1 alone fixes the fabrication bug.

### Tier 1 — Descriptive & aggregation

Closes the "chart numbers are invented" gap. No new dependencies.

`groupby_aggregate` (count/sum/mean/median/min/max/std/quantile) · `value_counts`
· `crosstab` · `describe` · `histogram` · `top_n` / `bottom_n` · `pivot` ·
`filter` (reuse the validated predicates in `manipulation_executor`) ·
`resample` (time-based rollup)

### Tier 2 — Bivariate

`correlation_matrix` (Pearson/Spearman/Kendall, with p-values) · `covariance` ·
`scatter_with_fit` (OLS line, R², optional `color_by` and bubble `size`, with a
computed reading of the fit; also served without the planner by
`POST /analysis/{id}/scatter`) · `group_comparison` (means + CI by group)

Adds: **scipy 1.18.1**

### Tier 3 — Inferential

`ttest` (one-sample, independent, paired, Welch) · `anova` · `kruskal` ·
`chi_square` (independence, goodness-of-fit) · `mannwhitney` · `wilcoxon` ·
`normality_test` (Shapiro–Wilk, D'Agostino) · `proportion_test`

Every result returns: statistic, p-value, **effect size**, **confidence
interval**, n, and **assumption checks**. A t-test reports Levene's test for
equal variance; the narrator is required to surface violations rather than bury
them. This is the line between a statistics tool and a plausible-looking one.

### Tier 4 — Regression & econometrics

`ols` (robust SEs HC0–HC3, VIF, Breusch–Pagan, Durbin–Watson, residual plots) ·
`logit` / `probit` · `poisson` / `negative_binomial` · `quantile_regression` ·
`fixed_effects` / `random_effects` · `iv_2sls` · `diff_in_diff` (a constrained
OLS spec with the interaction term named explicitly)

Adds: **statsmodels 0.14.6**, **linearmodels 7.0** (panel + IV)

### Tier 5 — Time series

`decompose` (STL/seasonal) · `acf` / `pacf` · `adf_test` / `kpss_test` ·
`arima` / `sarimax` · `granger_causality` · `cointegration` (Engle–Granger,
Johansen)

### Tier 6 — Survey estimation

The highest-leverage tier for this product specifically. The cleaning ops are
already survey-shaped (`drop_incomplete_responses`, `sum_composite_expenses`,
`flag_contextual_fraud`) and `detect_domain` recognizes Qualtrics exports — but
none of that carries through to estimation.

`weighted_mean` / `weighted_total` (design weights) · `weighted_crosstab` with
Rao–Scott corrected chi-square · `design_effect` / effective sample size ·
`subpopulation_estimates` (correct domain estimation, not filter-then-analyze)

Unweighted means on a weighted survey are simply wrong, and no general-purpose
AI data tool handles this. It is the clearest differentiation available here.

## Cross-cutting requirements

**Provenance.** Every result carries the spec that produced it, n, n_excluded
and why, and library versions. Combined with the existing cleaning audit log,
that makes the full path from raw upload to reported number reproducible — and
exportable as a methods note.

**Code export.** Emit the equivalent Python (and R) for every executed spec.
This is the trust bridge: a researcher can rerun the analysis in their own
environment and confirm the number. It also makes DataPilot a legitimate
front-end to a real workflow rather than a walled garden.

**Multiple-comparison tracking.** Count tests run per session; offer
Benjamini–Hochberg or Bonferroni adjustment once the count climbs. Accidental
p-hacking is the default behavior of a chat interface over a dataset.

**Narrator constraints.** The step-4 prompt must forbid introducing any number
not present in the computed results, must state assumption violations, and must
distinguish association from causation. This prompt is a correctness surface,
not decoration — it needs tests.

**Execution path.** Tier 4–5 operations can run for minutes. The Celery job
infrastructure already handles cleaning and exports; route long analyses through
it rather than the request path. Tiers 1–3 stay synchronous.

## Phasing

| Phase | Content | Rough effort | Status |
|---|---|---|---|
| 1 | Spec→Validate→Execute→Narrate + Tier 1–2 | 2–3 weeks | **Shipped** |
| 2 | Tier 3 + assumption checks + provenance | 1.5–2 weeks | **Shipped** |
| 3 | Tier 4 + code export | 2–3 weeks | **Shipped** |
| 4 | Tier 5 + Tier 6 + multiple-comparison tracking | 2–3 weeks | **Shipped** |

### Phase 1 as built

- `analysis_spec.py` — the operation registry and validator. The planner prompt's
  capability list is generated from `OPERATIONS`, so the prompt cannot drift from
  what the validator accepts.
- `analysis_executor.py` — deterministic pandas/scipy execution, each result
  carrying `n`, `n_excluded`, and notes.
- `analysis.py` — plan (with a regenerate-on-rejection loop), execute, narrate.
- Eleven operations: `describe`, `groupby_aggregate`, `value_counts`, `crosstab`
  (with chi-square), `histogram`, `top_n`, `pivot`, `resample`,
  `correlation_matrix` (with pairwise p-values), `scatter_with_fit` (OLS + R²),
  `group_comparison` (95% CIs + Welch's t-test or one-way ANOVA).
- The response contract (`answer`, `charts`, `tables`) is unchanged, so the
  frontend needed no rewrite — what changed is that the values are measured.

Verified end-to-end against a 480-row dataset with independently computed ground
truth: regional totals, segment means, both confidence-interval bounds, sample
sizes, and the t-statistic all matched exactly, and the pipeline correctly
refused a question the data could not answer.

### Phase 2 as built

Nineteen operations now, eight of them inferential. Every Tier 3 result carries
the same four things beside its statistic — effect size, confidence interval,
assumption checks, and n — because a p-value alone invites the two commonest
mistakes in applied statistics: reading significance as importance, and running
a test whose assumptions the data violate.

- `analysis_stats.py` — effect sizes, intervals, and assumption checks as pure
  functions over arrays. Free of pandas and of the operation registry, so they
  read as statistics rather than as pipeline plumbing.
- `analysis_prep.py` — group splitting and summarizing, shared by every test.
  Groups come back in sorted label order, so the sign of a reported difference
  is stable and explainable rather than dependent on row order in the upload.
- `analysis_inference.py` — `ttest` (one-sample / independent / paired),
  `anova` (with Tukey HSD post-hoc), `kruskal`, `mannwhitney`, `wilcoxon`,
  `normality_test`.
- `analysis_categorical.py` — `chi_square` (independence with Cramér's V and an
  exact Fisher result for 2x2 tables, or goodness-of-fit), `proportion_test`
  (one- and two-sample, Wilson and Newcombe intervals, Cohen's h).
- `analysis_provenance.py` — the record behind an answer, rendered as a methods
  note. Deterministic by construction: a methods note written by the thing whose
  trustworthiness it attests to would be worth nothing.
- `analysis_result.py` — the shared result type, extracted so descriptive and
  inferential execution have one definition of what a result is.

**Assumption checks are three-valued.** `true`, `false`, and `null` — where null
means the check could not be evaluated, which is not the same as passing. The
narrator prompt requires every failed check to appear in the answer, in the same
breath as the finding it undermines rather than as a closing caveat.

**Refusal over degradation.** An independent t-test over three groups raises and
names ANOVA rather than silently comparing the first two. A `success_value` that
does not occur in the column is rejected by the validator with the real category
list, so the model can correct it, instead of surfacing as a rate of zero.

**Multiple comparisons**, listed below as a Phase 4 item, arrived early because
it costs thirty lines and belongs with the honesty work: p-values across the
tests in one answer are adjusted by Benjamini-Hochberg, and the narrator is told
to treat the adjusted value as the one that decides significance. Session-level
tracking across turns is still Phase 4.

**Category discovery.** `ColumnRoles` now carries the distinct values of
low-cardinality text columns (bounded: 30 columns, 50 values, 200k rows), so a
filter on `"Weest"` is rejected with the real spellings rather than silently
returning an empty frame that makes every downstream operation fail for reasons
unrelated to the question.

Two defects were found and fixed while verifying:

- P-values below the rounding precision serialized as `0.0`. A methods note
  reading `p = 0` claims certainty no test can support. Values below 1e-4 now
  keep significant figures rather than decimal places.
- Dropped incomplete pairs were reported as a *failed* assumption, which under
  the narrator's rules would have had routine missingness described as
  undermining the result. It is now "not evaluated", with the count and the
  condition under which it would matter.

Verified end-to-end against a 600-row dataset: t/F/z/chi-square statistics,
degrees of freedom, Cohen's d, eta and omega squared, Cramér's V, Cohen's h,
both CI bounds, and every group mean and proportion matched statistics computed
independently from the raw arrays. `z²` equalled the uncorrected chi-square on
the same table, as it must.

Phase 3 is the next meaningful step: Tier 4 regression, and code export — the
trust bridge that lets a researcher rerun the analysis in their own
environment.

### Phases 3 and 4 as built

Thirty-three operations. The registry became self-declaring first: `Param`,
`OperationDef` and `ColumnRoles` moved to `analysis_registry.py`, so a tier
module declares its operations beside the code that runs them and
`analysis_spec.py` merges them. Adding a tier is one new file rather than
coordinated edits to the whitelist, the dispatch table and the prompt — which is
also what let three tiers be written concurrently without collision.

- **Tier 4** (`analysis_regression.py`) — `ols`, `logit`, `count_model`,
  `quantile_regression`, with robust standard errors, VIF, Breusch-Pagan,
  Durbin-Watson, Jarque-Bera and Cook's distance. Perfect separation refuses.
- **Tier 5** (`analysis_timeseries.py`) — `decompose`, `stationarity_test`,
  `autocorrelation`, `arima`, `granger_causality`, over a shared regular-grid
  preparation step that reports the frequency it inferred, the duplicates it
  collapsed and the gaps it interpolated. A forecast always carries its interval.
- **Tier 6** (`analysis_survey.py`) — `weighted_mean`, `weighted_total`,
  `weighted_crosstab` with the Rao-Scott correction, `design_effect`, and
  `subpopulation_estimate` as genuine domain estimation. Taylor linearisation,
  design-based degrees of freedom, strata and clusters honoured.
- **Code export** (`analysis_codegen*.py`) — Python and R for all 33
  operations, attached to each answer's provenance. Tests execute the generated
  Python against the same frame and compare it with the pipeline's own output,
  so fidelity is a test condition. A coverage test makes an un-exportable tier a
  failure rather than a silent gap.
- **Planner briefing** (`analysis_briefing.py`) — measured structure fed to the
  planner: weight candidates, repeated respondent ids, group sizes, skewness,
  date regularity. Aimed squarely at the "wrong test selection" risk below.

**The audit mattered more than any single tier.** An independent pass over the
shipped Tier 1-3 code reproduced ten defects the 875-test suite passed clean
over — pre-rounded p-values serialising as `p = 0`, a group comparison that
dropped singleton groups from its test while showing them in the table, a
one-way ANOVA reported where Levene's test had already failed (and where Welch's
reverses the conclusion), an `n` that survived the nulls pandas had dropped, and
a methods note that misattributed parameters after a failed operation. Each is
fixed with a regression test. The lesson worth keeping: the core statistics were
sound — every formula the audit checked against scipy and statsmodels held — and
the defects clustered in the plumbing around them, in rounding, denominators,
indices and labels. That is where to look next time.

Verified end to end against data with known answers: `ols` recovered the
coefficients of a constructed linear model to four decimals against an
independent fit, `decompose` recovered a known seasonal amplitude and trend
slope, `weighted_mean` matched a hand-computed weighted average, and
`design_effect` matched Kish's closed form exactly.

## Risks

- **Wrong test selection.** The residual risk after all of the above: the model
  picks a valid-but-inappropriate test. Mitigations: require a `rationale` field
  in the spec, surface assumption checks in the output, and have the narrator
  state limitations. Cannot be eliminated — which is why code export matters.
- **Scale.** 50 MB cap and single-machine pandas is fine for survey work and
  Tier 4–5. If datasets grow, back Tier 1 aggregation with DuckDB; not needed
  now.
- **Whitelist expressiveness.** Some questions will not fit the operation set.
  The refusal path must be genuinely good, and the whitelist should grow from
  observed failures rather than speculation.
- **Latency and cost.** Analysis becomes 2 LLM calls (plan + narrate) plus
  compute, instead of 1. The plan call is small; the narrate call sees only
  results, not raw data. Net token use should drop, since 20 sample rows and a
  full profile no longer ride along on every turn.

## Out of scope

Machine learning (classification, clustering, forecasting beyond ARIMA),
causal inference beyond DiD/IV, Bayesian methods, and dashboards. Each is
defensible later; none belongs in the work that makes the current numbers real.
