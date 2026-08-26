# Scope: real statistical analysis

_Drafted 2026-08-26. Status: proposed, not started._

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
`scatter_with_fit` (OLS line, R²) · `group_comparison` (means + CI by group)

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

| Phase | Content | Rough effort |
|---|---|---|
| 1 | Spec→Validate→Execute→Narrate + Tier 1–2 | 2–3 weeks |
| 2 | Tier 3 + assumption checks + provenance | 1.5–2 weeks |
| 3 | Tier 4 + code export | 2–3 weeks |
| 4 | Tier 5 + Tier 6 + multiple-comparison tracking | 2–3 weeks |

Phase 1 is the one that matters. Until it ships, the honest position is that the
analysis tab produces illustrations, not findings — and it should probably say
so in the UI in the meantime.

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
