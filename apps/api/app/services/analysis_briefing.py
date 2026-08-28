"""What the planner is told about the dataset before it chooses an operation.

The validator in :mod:`app.services.analysis_spec` rejects a spec that is
malformed or names a column that does not exist. It cannot reject one that is
well-formed and statistically inappropriate — an unweighted mean on a survey
that shipped a design weight, an independent test on rows that repeat each
respondent twice, a Pearson correlation on a variable with a skewness of four.
Those choices are made one step earlier, from whatever the planner knows about
the data. Until now that was a univariate profile and ten sample rows, which say
nothing about analytic *structure*.

This module computes that structure and renders it as a compact block for the
planner prompt. Three rules keep it worth trusting:

**Factual, never advisory.** "3 levels, smallest 4 rows" is a fact the model can
act on. "Use Kruskal-Wallis" is a rule, and rules belong in the prompt where
they can be reviewed — not in generated text nobody reads. Nothing here names an
operation or recommends one.

**Nothing new is exposed.** Aggregates and category labels only. The pipeline
already sends a profile and a sample of rows; an identifier column is described
by its shape (400 distinct values, one row each) and never by its values.

**Bounded cost.** This runs in the request path on every analysis turn.
Distribution statistics come from a fixed-seed sample of at most
:data:`SCAN_SAMPLE_ROWS` rows, at most :data:`MAX_SCANNED_COLUMNS` columns are
profiled, and the facts a sample would misstate — how often a key repeats, how
large the smallest group is, how far a date column spans — are recomputed
exactly over the full column, for the handful of columns that get reported.
Measured at roughly 0.15 s of CPU for a 200,000 x 40 frame; the budget is one
second, and :func:`briefing_text` swallows its own failures because a missing
briefing must never cost an answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.services.analysis_result import clean_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost budget
# ---------------------------------------------------------------------------

# Rows used for distribution statistics. At n = 20,000 the standard error of a
# skewness estimate is sqrt(6/n) ~ 0.017 and of a proportion at most 0.35
# percentage points — an order of magnitude finer than any threshold here turns
# on, so a larger sample would buy precision nobody can use.
SCAN_SAMPLE_ROWS = 20_000

# Fixed, so the same file briefs identically on every turn of a conversation.
# A briefing that moved between turns would read as the data having changed.
SAMPLE_SEED = 20_250_827

# Columns given a per-column scan. Past this the count is reported and the
# columns are not described; weight-, identifier- and date-shaped columns are
# scanned first, so the cap cannot hide the ones that decide an operation.
MAX_SCANNED_COLUMNS = 60

# Missingness is exact whenever the frame is small enough to test every cell,
# which the product's 50 MB upload cap makes the ordinary case.
MAX_MISSINGNESS_CELLS = 50_000_000

# Per-section output caps. The briefing goes into a prompt, so it is bounded by
# ranking and truncating rather than by emitting everything and hoping.
MAX_WEIGHT_CANDIDATES = 3
MAX_KEY_COLUMNS = 4
MAX_DATE_COLUMNS = 3
MAX_GROUP_COLUMNS = 6
MAX_NUMERIC_COLUMNS = 8
MAX_ORDINAL_COLUMNS = 8
MAX_MISSING_COLUMNS = 5
MAX_LOW_INFORMATION_COLUMNS = 5

# Hard ceiling on the rendered block: roughly a thousand tokens at four
# characters each. A typical file lands near a quarter of it.
MAX_BRIEFING_CHARS = 4_000

# ---------------------------------------------------------------------------
# Detection thresholds
# ---------------------------------------------------------------------------

# Below this many observations skewness and kurtosis describe the sample rather
# than the distribution, so no shape is reported at all.
MIN_SHAPE_ROWS = 8

# Bulmer's conventional bands for the magnitude of sample skewness.
SKEW_MODERATE = 0.5
SKEW_HIGH = 1.0

# A grouping column: few enough levels to compare, and levels that actually
# repeat — three distinct values over three rows is an identifier, not a group.
MAX_GROUP_LEVELS = 12
MIN_ROWS_PER_LEVEL = 2

# A column holding one value in 98% of rows cannot separate anything. Below ten
# rows the claim would be about the sample rather than about the column.
NEAR_CONSTANT_SHARE = 0.98
NEAR_CONSTANT_MIN_ROWS = 10

# Near-unique text: free-form entry rather than a category.
HIGH_CARDINALITY_SHARE = 0.9
HIGH_CARDINALITY_MIN_DISTINCT = 50

# A trend through fewer points than this has almost no residual degrees of
# freedom, and a seasonal decomposition needs two whole cycles on top. This is a
# statement about how many distinct time points exist, not a recommendation.
MIN_TREND_POINTS = 8

# Calendar months differ in length by construction, so "regular" spacing is a
# tolerance on the coefficient of variation of the gaps rather than equality.
REGULARITY_CV = 0.05
MIN_GAPS_FOR_REGULARITY = 3

# Design weights are normalized to average one; population-expansion weights
# instead sum to a population, which puts their mean far above one.
WEIGHT_MEAN_LOW, WEIGHT_MEAN_HIGH = 0.5, 2.0
WEIGHT_POPULATION_MEAN = 10.0
# Real design weights are trimmed. A ratio wider than this is some other ratio.
WEIGHT_MAX_RATIO = 1_000.0

# Likert tops that occur in practice: 1-4, 1-5, 1-7, 1-10, plus 0-10 (NPS).
LIKERT_TOPS = (4, 5, 7, 10)
LIKERT_MIN_LEVELS = 3
NPS_TOP = 10
NPS_MIN_LEVELS = 8

MAX_ORDINAL_LEVELS = 9
MIN_ORDINAL_LABEL_MATCHES = 2
MIN_ORDINAL_LABEL_SHARE = 0.5

_WEIGHT_TOKENS = frozenset(
    {"weight", "weights", "wt", "wts", "wgt", "wgts", "wght", "pweight", "pwgt", "finalwt", "fwt"}
)

# Tokens that say the column is a measured weight rather than a design weight.
_PHYSICAL_WEIGHT_TOKENS = frozenset(
    {
        "kg", "kgs", "lb", "lbs", "g", "gram", "grams", "oz", "ounce", "ounces",
        "pound", "pounds", "ton", "tons", "tonne", "tonnes", "kilo", "kilos",
        "birth", "body", "net", "gross", "shipping", "ship", "parcel", "package", "cargo",
    }
)  # fmt: skip

_IDENTIFIER_TOKENS = frozenset(
    {
        "id", "ids", "uuid", "guid", "key", "respondent", "record", "case",
        "subject", "participant", "pid", "hhid", "serial",
    }
)  # fmt: skip

# Ordered response labels. A column whose levels are mostly drawn from this is
# ordinal however it happens to be stored.
_ORDINAL_LABELS = frozenset(
    {
        "strongly agree", "agree", "somewhat agree", "slightly agree",
        "neither agree nor disagree", "neutral", "neither",
        "somewhat disagree", "slightly disagree", "disagree", "strongly disagree",
        "very satisfied", "satisfied", "dissatisfied", "very dissatisfied",
        "never", "rarely", "sometimes", "often", "very often", "always",
        "not at all", "a little", "somewhat", "a lot", "very much",
        "excellent", "very good", "good", "fair", "poor", "very poor",
        "strongly approve", "approve", "disapprove", "strongly disapprove",
        "much better", "better", "about the same", "worse", "much worse",
    }
)  # fmt: skip

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(name: str) -> frozenset[str]:
    return frozenset(part for part in _TOKEN_SPLIT.split(name.lower()) if part)


def _is_weight_name(name: str) -> bool:
    lowered = name.lower()
    return bool(_tokens(name) & _WEIGHT_TOKENS) or "weight" in lowered or "wgt" in lowered


def _is_identifier_name(name: str) -> bool:
    lowered = name.lower()
    if _tokens(name) & _IDENTIFIER_TOKENS:
        return True
    return lowered.endswith("id") or "uuid" in lowered


# ---------------------------------------------------------------------------
# The briefing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeightCandidate:
    """A column that may carry survey design weights, with the evidence for it."""

    column: str
    confidence: str  # high | moderate | low
    reason: str
    n: int
    mean: float | None
    minimum: float | None
    maximum: float | None
    total: float | None
    integer_valued: bool


@dataclass(frozen=True)
class KeyColumn:
    """How often a candidate identifier repeats — paired data's fingerprint."""

    column: str
    rows: int
    distinct: int
    row_unique: bool
    max_rows_per_value: int
    uniform_repeat: bool


@dataclass(frozen=True)
class DateColumn:
    """A datetime column's span, granularity, and how many points it offers."""

    column: str
    start: str | None
    end: str | None
    distinct: int
    median_gap_days: float | None
    regular: bool
    too_sparse_for_trend: bool


@dataclass(frozen=True)
class NumericColumn:
    """The shape of one numeric column, as statistics rather than as a verdict."""

    column: str
    n: int
    skewness: float | None
    excess_kurtosis: float | None
    shape: str  # symmetric | moderately skewed | highly skewed | unknown
    zero_share: float
    kind: str  # continuous | count | binary


@dataclass(frozen=True)
class GroupingColumn:
    column: str
    levels: int
    min_group_size: int
    max_group_size: int
    smallest_level: str


@dataclass(frozen=True)
class OrdinalColumn:
    column: str
    kind: str  # integer_scale | labelled
    levels: int
    minimum: int | None
    maximum: int | None


@dataclass(frozen=True)
class MissingColumn:
    column: str
    rate: float


@dataclass(frozen=True)
class Missingness:
    """Per-column rates, plus what listwise deletion would actually cost."""

    columns: tuple[MissingColumn, ...]
    omitted: int
    incomplete_row_share: float
    mean_missing_fields_in_incomplete_rows: float | None
    fields: int
    sampled: bool = False


@dataclass(frozen=True)
class LowInformationColumn:
    column: str
    reason: str  # near-constant | high-cardinality
    detail: str


@dataclass(frozen=True)
class DatasetBriefing:
    """The dataset's analytic structure, as facts."""

    rows: int
    columns: int
    sampled_rows: int | None
    columns_not_scanned: int
    duplicate_column_names: tuple[str, ...]
    weights: tuple[WeightCandidate, ...]
    keys: tuple[KeyColumn, ...]
    dates: tuple[DateColumn, ...]
    numeric: tuple[NumericColumn, ...]
    numeric_omitted: int
    groups: tuple[GroupingColumn, ...]
    groups_omitted: int
    ordinal: tuple[OrdinalColumn, ...]
    ordinal_omitted: int
    missingness: Missingness
    low_information: tuple[LowInformationColumn, ...]
    has_numeric_columns: bool

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe dict — for tests, and for anything that logs the briefing."""
        return clean_stats(_to_lists(asdict(self)))


def _to_lists(value: Any) -> Any:
    """Turn the tuples ``asdict`` preserves into JSON-safe lists."""
    if isinstance(value, dict):
        return {key: _to_lists(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_lists(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scan:
    """One column as the scan saw it — over a sample, for a large dataset."""

    name: str
    position: int
    role: str  # numeric | datetime | boolean | categorical
    n: int
    null_rate: float
    distinct: int
    dominant_share: float
    smallest_level: str
    min_count: int
    max_count: int
    labels: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    skewness: float | None = None
    excess_kurtosis: float | None = None
    zero_share: float = 0.0
    integer_valued: bool = False


def _role(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    return "categorical"


def _sample_indices(rows: int) -> np.ndarray | None:
    """Row positions for the scan, or None when the whole frame is affordable.

    Sorted, because taking rows in file order is markedly cheaper than taking
    them in random order and the result is the same set of rows.
    """
    if rows <= SCAN_SAMPLE_ROWS:
        return None
    generator = np.random.default_rng(SAMPLE_SEED)
    return np.sort(generator.choice(rows, SCAN_SAMPLE_ROWS, replace=False))


def _scan_order(df: pd.DataFrame) -> tuple[list[int], int]:
    """Positions to scan — decisive columns first — and how many were left out.

    Only the first column of each duplicated name is scanned: the validator and
    the executor address columns by name, so a second column called ``a`` cannot
    be analyzed, and describing it would only make the briefing ambiguous.
    """
    seen: set[str] = set()
    decisive: list[int] = []
    ordinary: list[int] = []
    for position, name in enumerate(df.columns):
        text = str(name)
        if text in seen:
            continue
        seen.add(text)
        first = (
            _is_weight_name(text)
            or _is_identifier_name(text)
            or pd.api.types.is_datetime64_any_dtype(df.iloc[:, position])
        )
        (decisive if first else ordinary).append(position)

    ordered = decisive + ordinary
    return ordered[:MAX_SCANNED_COLUMNS], max(0, len(ordered) - MAX_SCANNED_COLUMNS)


def _numeric_facts(values: np.ndarray) -> dict[str, Any]:
    """Shape statistics for a finite numeric array, Nones where undefined.

    pandas' ``skew``/``kurt`` are the bias-corrected G1 and G2 — identical to
    ``scipy.stats.skew(bias=False)`` and ``kurtosis(fisher=True, bias=False)``
    to ten decimal places, and cheaper, since they run in Cython over the array
    rather than through scipy's axis/nan-policy wrapper.
    """
    if values.size == 0:
        return {}
    facts: dict[str, Any] = {
        "minimum": float(values.min()),
        "maximum": float(values.max()),
        "mean": float(values.mean()),
        "zero_share": float(np.mean(values == 0.0)),
        "integer_valued": bool(np.all(np.mod(values, 1.0) == 0.0)),
    }
    # Skewness of a constant column is 0/0. Reporting the 0.0 pandas returns
    # would say "symmetric" about a column that has no distribution at all.
    if values.size >= MIN_SHAPE_ROWS and values.std() > 0:
        wrapped = pd.Series(values)
        facts["skewness"] = _finite(wrapped.skew())
        facts["excess_kurtosis"] = _finite(wrapped.kurt())
    return facts


def _finite(value: Any) -> float | None:
    as_float = float(value)
    return as_float if np.isfinite(as_float) else None


def _scan_column(df: pd.DataFrame, position: int, indices: np.ndarray | None) -> _Scan:
    series = df.iloc[:, position]
    if indices is not None:
        series = series.take(indices)
    rows = len(series)
    non_null = int(series.notna().sum())
    role = _role(series)

    counts = pd.Series(dtype="int64")
    if role != "datetime" and non_null:
        raw = series.value_counts(dropna=True)
        counts = raw[raw > 0]  # a categorical dtype reports unobserved levels

    facts: dict[str, Any] = {}
    if role == "numeric" and non_null:
        values = series.dropna().to_numpy(dtype=float)
        facts = _numeric_facts(values[np.isfinite(values)])

    labels = (
        tuple(str(label) for label in counts.index)
        if role == "categorical" and 0 < counts.size <= MAX_ORDINAL_LEVELS
        else ()
    )
    return _Scan(
        name=str(df.columns[position]),
        position=position,
        role=role,
        n=non_null,
        null_rate=float(rows - non_null) / rows if rows else 0.0,
        distinct=int(counts.size),
        dominant_share=float(counts.iloc[0]) / non_null if counts.size and non_null else 0.0,
        smallest_level=str(counts.index[-1]) if counts.size else "",
        min_count=int(counts.iloc[-1]) if counts.size else 0,
        max_count=int(counts.iloc[0]) if counts.size else 0,
        labels=labels,
        **facts,
    )


def _exact_counts(df: pd.DataFrame, position: int) -> pd.Series:
    counts = df.iloc[:, position].value_counts(dropna=True)
    return counts[counts > 0]


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _weight_evidence(values: np.ndarray, name: str) -> tuple[str, str]:
    """Confidence that *values* are design weights, and the evidence either way.

    A matching name is not evidence: ``weight_kg`` in a health file is the
    commonest false positive there is. The discriminating fact is the mean —
    design weights are normalized to average one, or sum to a population — and
    the second is that they are fractional. Both are reported whatever the
    verdict, so a wrong call is visible rather than asserted.
    """
    mean, low, high = float(values.mean()), float(values.min()), float(values.max())
    integral = bool(np.all(np.mod(values, 1.0) == 0.0))
    ratio = high / low if low > 0 else float("inf")
    physical = sorted(_tokens(name) & _PHYSICAL_WEIGHT_TOKENS)

    detail = (
        f"{values.size:,} values, all positive, mean {mean:.3g}, range {low:.3g}-{high:.3g}, "
        f"{'integer-valued' if integral else 'fractional'}"
    )
    if high == low:
        return "low", f"constant {mean:.4g}; {detail}"

    normalized = WEIGHT_MEAN_LOW <= mean <= WEIGHT_MEAN_HIGH
    population_scale = mean >= WEIGHT_POPULATION_MEAN
    bounded = ratio <= WEIGHT_MAX_RATIO

    confidence = "low"
    if normalized and not integral and bounded:
        confidence = "high"
    elif (normalized and bounded) or (population_scale and not integral and bounded):
        confidence = "moderate"

    reasons = [detail]
    if physical:
        # A physical-unit token means a measured weight. Demote rather than
        # exclude: the evidence still belongs in front of the model.
        confidence = {"high": "moderate", "moderate": "low"}.get(confidence, confidence)
        reasons.append(f"name contains a physical-unit token ({', '.join(physical)})")
    if confidence == "low" and not physical:
        reasons.append("values do not resemble design weights")
    return confidence, "; ".join(reasons)


def _weights(df: pd.DataFrame, scans: tuple[_Scan, ...]) -> tuple[WeightCandidate, ...]:
    """Columns whose name matches a weight pattern, judged on their real values.

    The statistics come from the full column, never the sample: "every value is
    positive" is a claim about every value, and a sample cannot make it.
    """
    found: list[WeightCandidate] = []
    for scan in scans:
        if len(found) >= MAX_WEIGHT_CANDIDATES:
            break
        if scan.role != "numeric" or not _is_weight_name(scan.name):
            continue
        values = df.iloc[:, scan.position].dropna().to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        # A weight of zero drops a respondent and a negative weight has no
        # interpretation at all; either one means this column is something else.
        if values.size == 0 or values.min() <= 0:
            continue
        confidence, reason = _weight_evidence(values, scan.name)
        found.append(
            WeightCandidate(
                column=scan.name,
                confidence=confidence,
                reason=reason,
                n=int(values.size),
                mean=float(values.mean()),
                minimum=float(values.min()),
                maximum=float(values.max()),
                total=float(values.sum()),
                integer_valued=bool(np.all(np.mod(values, 1.0) == 0.0)),
            )
        )
    rank = {"high": 0, "moderate": 1, "low": 2}
    return tuple(
        sorted(found, key=lambda candidate: (rank[candidate.confidence], candidate.column))
    )


def _keys(df: pd.DataFrame, scans: tuple[_Scan, ...]) -> tuple[KeyColumn, ...]:
    """Identifier-shaped columns, and how often their values repeat.

    Repetition is what separates paired data from independent data, and it is
    exactly what a sample destroys: two rows per respondent look like one row
    per respondent once you keep a twentieth of the rows. So these counts come
    from the full column, for a bounded number of candidates.
    """
    candidates = [
        scan
        for scan in scans
        if _is_identifier_name(scan.name)
        or (scan.role == "numeric" and scan.integer_valued and scan.n and scan.distinct == scan.n)
    ]
    found: list[KeyColumn] = []
    for scan in candidates[: MAX_KEY_COLUMNS * 2]:
        counts = _exact_counts(df, scan.position)
        if counts.empty:
            continue
        distinct, largest, smallest = int(counts.size), int(counts.iloc[0]), int(counts.iloc[-1])
        found.append(
            KeyColumn(
                column=scan.name,
                rows=len(df),
                distinct=distinct,
                row_unique=bool(largest == 1 and distinct == len(df)),
                max_rows_per_value=largest,
                uniform_repeat=bool(largest == smallest and largest > 1),
            )
        )
    # A repeating identifier changes which comparisons are appropriate; a unique
    # one only rules things out, so it is reported second.
    found.sort(key=lambda key: (key.row_unique, -key.distinct))
    return tuple(found[:MAX_KEY_COLUMNS])


def _date_column(df: pd.DataFrame, scan: _Scan) -> DateColumn | None:
    series = df.iloc[:, scan.position].dropna()
    if series.empty:
        return None
    ordered = pd.DatetimeIndex(series.unique()).sort_values()
    # Dividing by a Timedelta rather than reading int64 keeps this correct for
    # any datetime resolution pandas hands over (second, microsecond, nano).
    gaps = np.asarray((ordered[1:] - ordered[:-1]) / pd.Timedelta(days=1), dtype=float)

    median_gap, regular = None, False
    if gaps.size:
        median_gap = float(np.median(gaps))
        if gaps.size >= MIN_GAPS_FOR_REGULARITY:
            mean_gap = float(gaps.mean())
            regular = bool(mean_gap > 0 and float(gaps.std()) / mean_gap <= REGULARITY_CV)

    return DateColumn(
        column=scan.name,
        start=ordered[0].isoformat(),
        end=ordered[-1].isoformat(),
        distinct=int(ordered.size),
        median_gap_days=median_gap,
        regular=regular,
        too_sparse_for_trend=bool(ordered.size < MIN_TREND_POINTS),
    )


def _dates(df: pd.DataFrame, scans: tuple[_Scan, ...]) -> tuple[DateColumn, ...]:
    found = [
        column
        for scan in scans
        if scan.role == "datetime"
        for column in [_date_column(df, scan)]
        if column is not None
    ]
    return tuple(found[:MAX_DATE_COLUMNS])


def _ordinal(scan: _Scan) -> OrdinalColumn | None:
    """A Likert-shaped integer scale, or a column of ordered response labels."""
    if scan.role == "numeric":
        if not scan.integer_valued or scan.minimum is None or scan.maximum is None:
            return None
        low, high, levels = int(scan.minimum), int(scan.maximum), scan.distinct
        if low == 1 and high in LIKERT_TOPS and levels >= min(LIKERT_MIN_LEVELS, high):
            return OrdinalColumn(scan.name, "integer_scale", levels, low, high)
        if low == 0 and high == NPS_TOP and levels >= NPS_MIN_LEVELS:
            return OrdinalColumn(scan.name, "integer_scale", levels, low, high)
        return None

    if scan.role != "categorical" or not 2 <= scan.distinct <= MAX_ORDINAL_LEVELS:
        return None
    matched = sum(1 for label in scan.labels if label.strip().lower() in _ORDINAL_LABELS)
    if matched >= MIN_ORDINAL_LABEL_MATCHES and matched / scan.distinct >= MIN_ORDINAL_LABEL_SHARE:
        return OrdinalColumn(scan.name, "labelled", scan.distinct, None, None)
    return None


def _shape_word(skewness: float | None) -> str:
    if skewness is None:
        return "unknown"
    if abs(skewness) < SKEW_MODERATE:
        return "symmetric"
    return "moderately skewed" if abs(skewness) < SKEW_HIGH else "highly skewed"


def _numeric_kind(scan: _Scan) -> str:
    if scan.distinct == 2:
        return "binary"
    if scan.integer_valued and scan.minimum is not None and scan.minimum >= 0:
        return "count"
    return "continuous"


def _numeric(
    scans: tuple[_Scan, ...], skip: frozenset[str]
) -> tuple[tuple[NumericColumn, ...], int]:
    """Distribution shape per numeric column, most lopsided first."""
    described = [
        NumericColumn(
            column=scan.name,
            n=scan.n,
            skewness=scan.skewness,
            excess_kurtosis=scan.excess_kurtosis,
            shape=_shape_word(scan.skewness),
            zero_share=scan.zero_share,
            kind=_numeric_kind(scan),
        )
        for scan in scans
        if scan.role == "numeric" and scan.n >= MIN_SHAPE_ROWS and scan.name not in skip
    ]
    described.sort(key=lambda column: -abs(column.skewness or 0.0))
    return tuple(described[:MAX_NUMERIC_COLUMNS]), max(0, len(described) - MAX_NUMERIC_COLUMNS)


def _groups(
    df: pd.DataFrame, scans: tuple[_Scan, ...], sampled: bool, skip: frozenset[str]
) -> tuple[tuple[GroupingColumn, ...], int]:
    """Low-cardinality columns with their exact level sizes.

    The smallest level decides whether a comparison is possible at all, so the
    sizes are recomputed over the full column for the ones reported: a level of
    four rows can vanish from a sample entirely.
    """
    candidates = [
        scan
        for scan in scans
        if scan.role in ("categorical", "boolean", "numeric")
        and 2 <= scan.distinct <= MAX_GROUP_LEVELS
        and scan.n >= scan.distinct * MIN_ROWS_PER_LEVEL
        and scan.name not in skip
    ]
    candidates.sort(key=lambda scan: (scan.min_count, scan.name))

    described: list[GroupingColumn] = []
    for scan in candidates[:MAX_GROUP_COLUMNS]:
        counts = _exact_counts(df, scan.position) if sampled else None
        levels = int(counts.size) if counts is not None else scan.distinct
        if counts is not None and not 2 <= levels <= MAX_GROUP_LEVELS:
            continue
        described.append(
            GroupingColumn(
                column=scan.name,
                levels=levels,
                min_group_size=int(counts.iloc[-1]) if counts is not None else scan.min_count,
                max_group_size=int(counts.iloc[0]) if counts is not None else scan.max_count,
                smallest_level=str(counts.index[-1]) if counts is not None else scan.smallest_level,
            )
        )
    return tuple(described), max(0, len(candidates) - len(described))


def _missingness(df: pd.DataFrame, indices: np.ndarray | None) -> Missingness:
    """Per-column rates, and how concentrated the gaps are across rows.

    Whether missingness is scattered over many rows or concentrated in a few
    decides what listwise deletion costs: 5% missing in every column can mean
    losing 5% of rows or 40% of them, and only one of those is affordable.
    """
    if not len(df.columns):
        return Missingness((), 0, 0.0, None, 0)

    frame, sampled = df, False
    if len(df) * len(df.columns) > MAX_MISSINGNESS_CELLS and indices is not None:
        frame, sampled = df.take(indices), True

    missing = frame.isna()
    ranked = [
        MissingColumn(column=str(name), rate=float(rate))
        for name, rate in missing.mean().sort_values(ascending=False).items()
        if float(rate) > 0
    ]
    per_row = missing.sum(axis=1).to_numpy()
    incomplete = per_row > 0
    return Missingness(
        columns=tuple(ranked[:MAX_MISSING_COLUMNS]),
        omitted=max(0, len(ranked) - MAX_MISSING_COLUMNS),
        incomplete_row_share=float(incomplete.mean()) if per_row.size else 0.0,
        mean_missing_fields_in_incomplete_rows=(
            float(per_row[incomplete].mean()) if incomplete.any() else None
        ),
        fields=len(frame.columns),
        sampled=sampled,
    )


def _low_information(
    scans: tuple[_Scan, ...], skip: frozenset[str]
) -> tuple[LowInformationColumn, ...]:
    """Columns that cannot serve as a group or a predictor, so nothing proposes them."""
    found: list[LowInformationColumn] = []
    for scan in scans:
        if scan.name in skip or not scan.n:
            continue
        if scan.n >= NEAR_CONSTANT_MIN_ROWS and scan.dominant_share >= NEAR_CONSTANT_SHARE:
            detail = (
                "1 distinct value"
                if scan.distinct == 1
                else f"{scan.dominant_share * 100:.0f}% of rows share one value"
            )
            found.append(LowInformationColumn(scan.name, "near-constant", detail))
        elif (
            scan.role == "categorical"
            and scan.distinct >= HIGH_CARDINALITY_MIN_DISTINCT
            and scan.distinct / scan.n >= HIGH_CARDINALITY_SHARE
        ):
            found.append(
                LowInformationColumn(
                    scan.name,
                    "high-cardinality",
                    f"{scan.distinct:,} distinct values over {scan.n:,} rows",
                )
            )
    return tuple(found[:MAX_LOW_INFORMATION_COLUMNS])


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_briefing(df: pd.DataFrame) -> DatasetBriefing:
    """Describe the analytic structure of *df*. Pure: the frame is not touched."""
    indices = _sample_indices(len(df))
    positions, not_scanned = _scan_order(df)
    scans = tuple(_scan_column(df, position, indices) for position in positions)

    weights = _weights(df, scans)
    keys = _keys(df, scans)
    dates = _dates(df, scans)
    ordinal_all = [column for scan in scans for column in [_ordinal(scan)] if column is not None]
    ordinal = tuple(ordinal_all[:MAX_ORDINAL_COLUMNS])

    identifiers = frozenset(key.column for key in keys)
    # A column already described as a key, a weight or a scale is not described
    # a second time: duplication in a prompt is noise that crowds out facts.
    described = (
        identifiers
        | frozenset(column.column for column in ordinal_all)
        | frozenset(w.column for w in weights if w.confidence != "low")
    )
    numeric, numeric_omitted = _numeric(scans, described)
    groups, groups_omitted = _groups(df, scans, indices is not None, described)

    return DatasetBriefing(
        rows=len(df),
        columns=len(df.columns),
        sampled_rows=None if indices is None else int(indices.size),
        columns_not_scanned=not_scanned,
        duplicate_column_names=tuple(
            dict.fromkeys(str(name) for name in df.columns[df.columns.duplicated()])
        ),
        weights=weights,
        keys=keys,
        dates=dates,
        numeric=numeric,
        numeric_omitted=numeric_omitted,
        groups=groups,
        groups_omitted=groups_omitted,
        ordinal=ordinal,
        ordinal_omitted=max(0, len(ordinal_all) - len(ordinal)),
        missingness=_missingness(df, indices),
        low_information=_low_information(scans, identifiers),
        has_numeric_columns=any(scan.role == "numeric" for scan in scans),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _n(value: int) -> str:
    return f"{value:,}"


def _pct(share: float) -> str:
    return f"{share * 100:.1f}%"


def _g(value: float | None, places: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{places}g}"


def _header(briefing: DatasetBriefing) -> list[str]:
    lines = [
        "=== Dataset structure (measured from the data, not inferred by a model) ===",
        f"{_n(briefing.rows)} rows x {_n(briefing.columns)} columns.",
    ]
    if briefing.sampled_rows:
        lines[-1] += (
            f" Distribution statistics come from a random sample of "
            f"{_n(briefing.sampled_rows)} rows; counts, ranges and level sizes are exact."
        )
    if briefing.columns_not_scanned:
        lines.append(
            f"{_n(briefing.columns - briefing.columns_not_scanned)} columns were profiled; "
            f"{_n(briefing.columns_not_scanned)} more are not described below."
        )
    if briefing.duplicate_column_names:
        lines.append(
            "Duplicated column name(s), which cannot be addressed unambiguously: "
            + ", ".join(briefing.duplicate_column_names)
        )
    return lines


def _weights_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.weights:
        if not briefing.has_numeric_columns:
            return []
        return [
            "Survey weights: no column name matched a weight pattern (weight, wt, wgt, pweight)."
        ]
    return ["Survey weight candidates:"] + [
        f"  {candidate.column} — {candidate.confidence} confidence: {candidate.reason}; "
        f"sum {_g(candidate.total, 6)}"
        for candidate in briefing.weights
    ]


def _keys_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.keys:
        return []
    lines = ["Row identity:"]
    for key in briefing.keys:
        span = f"{_n(key.distinct)} distinct values over {_n(key.rows)} rows"
        if key.row_unique:
            detail = f"{span}, one row each"
        elif key.uniform_repeat:
            detail = f"{span}, each appearing exactly {key.max_rows_per_value} times"
        else:
            detail = f"{span}, up to {_n(key.max_rows_per_value)} rows per value"
        lines.append(f"  {key.column} — {detail}")
    return lines


def _dates_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.dates:
        return ["Dates: no datetime-typed column."]
    lines = ["Dates:"]
    for date in briefing.dates:
        detail = (
            f"{date.start[:10]} to {date.end[:10]}, {_n(date.distinct)} distinct time points, "
            f"spacing {'regular' if date.regular else 'irregular'} "
            f"(median gap {_g(date.median_gap_days)} days)"
        )
        if date.too_sparse_for_trend:
            detail += f"; fewer than {MIN_TREND_POINTS} distinct points"
        lines.append(f"  {date.column} — {detail}")
    return lines


def _groups_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.groups:
        return []
    lines = ["Grouping columns (level sizes over all rows, before dropping missing values):"]
    for group in briefing.groups:
        if group.min_group_size == group.max_group_size:
            sizes = f"{_n(group.min_group_size)} rows each"
        else:
            sizes = (
                f"sizes {_n(group.min_group_size)}-{_n(group.max_group_size)}, "
                f'smallest "{group.smallest_level}"'
            )
        lines.append(f"  {group.column} — {group.levels} levels, {sizes}")
    if briefing.groups_omitted:
        lines.append(f"  ... and {_n(briefing.groups_omitted)} more grouping column(s).")
    return lines


def _numeric_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.numeric:
        return []
    lines = ["Numeric columns:"]
    for column in briefing.numeric:
        detail = (
            f"skew {_g(column.skewness)}, excess kurtosis {_g(column.excess_kurtosis)} "
            f"({column.shape}), {column.kind}"
        )
        if column.zero_share > 0:
            detail += f", {_pct(column.zero_share)} zeros"
        lines.append(f"  {column.column} — {detail}, n={_n(column.n)}")
    if briefing.numeric_omitted:
        lines.append(f"  ... and {_n(briefing.numeric_omitted)} more numeric column(s).")
    return lines


def _ordinal_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.ordinal:
        return []
    described = ", ".join(
        f"{column.column} ({column.minimum}-{column.maximum}, {column.levels} levels)"
        if column.kind == "integer_scale"
        else f"{column.column} (ordered labels, {column.levels} levels)"
        for column in briefing.ordinal
    )
    line = f"Ordinal / Likert-shaped columns: {described}"
    if briefing.ordinal_omitted:
        line += f", and {_n(briefing.ordinal_omitted)} more"
    return [line + "."]


def _missing_lines(briefing: DatasetBriefing) -> list[str]:
    missing = briefing.missingness
    if not missing.columns:
        return ["Missing values: none."]
    rates = ", ".join(f"{column.column} {_pct(column.rate)}" for column in missing.columns)
    if missing.omitted:
        rates += f", and {_n(missing.omitted)} more column(s)"
    line = f"Missing values: {rates}."
    if missing.mean_missing_fields_in_incomplete_rows is not None:
        line += (
            f" {_pct(missing.incomplete_row_share)} of rows have at least one missing value, "
            f"averaging {_g(missing.mean_missing_fields_in_incomplete_rows, 2)} "
            f"of {missing.fields} fields."
        )
    return [line]


def _low_information_lines(briefing: DatasetBriefing) -> list[str]:
    if not briefing.low_information:
        return []
    described = "; ".join(
        f"{column.column} ({column.detail})" for column in briefing.low_information
    )
    return [f"Low-information columns: {described}."]


def render_briefing(briefing: DatasetBriefing) -> str:
    """Render the briefing as the prompt block, capped at MAX_BRIEFING_CHARS."""
    sections = [
        _header(briefing),
        _weights_lines(briefing),
        _keys_lines(briefing),
        _dates_lines(briefing),
        _groups_lines(briefing),
        _numeric_lines(briefing),
        _ordinal_lines(briefing),
        _missing_lines(briefing),
        _low_information_lines(briefing),
    ]
    text = "\n".join(line for section in sections if section for line in section)
    if len(text) <= MAX_BRIEFING_CHARS:
        return text
    notice = "\n... (briefing truncated)"
    kept = text[: MAX_BRIEFING_CHARS - len(notice)]
    return kept[: kept.rfind("\n")] + notice


def briefing_text(df: pd.DataFrame) -> str:
    """The briefing as a prompt block — the one call the planner context needs.

    Never raises. A briefing is context: failing an entire analysis because a
    descriptive statistic could not be computed would trade a better plan for no
    answer at all. The failure is logged instead.
    """
    try:
        return render_briefing(build_briefing(df))
    except Exception:
        logger.exception("Dataset briefing could not be built; planning without it")
        return ""
