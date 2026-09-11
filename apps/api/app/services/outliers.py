"""Outlier policy — one source of truth for what counts as an outlier.

Two jobs live here, and keeping them apart matters:

*Detection* (:func:`detection_fences`) decides what to **show**: which cells the
preview grid reddens, and which columns the planner is told about. Its fences
reach deliberately far out, so ordinary variation is not paraded as an error.

*Policy* (:class:`OutlierPolicy`) decides what to **change**: the cutoff the
cleaning operations apply, and the cutoff verification re-checks them against.
Both read the same policy, so the two cannot drift apart — they did once, with
the cleaner flagging at 5.0 while verification re-checked at 3.5 and failed
steps that had behaved exactly as configured.

Both look at both tails. A price of 1 among four-figure prices is as much a
data-entry error as a 99999.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

OutlierMethod = Literal["mad", "iqr", "none"]

#: MAD modified-z cutoff used when the user has expressed no preference.
#: Deliberately forgiving — read tests/test_outlier_thresholds.py before moving it.
DEFAULT_THRESHOLD = 5.0

#: IQR reach for row-dropping (``remove_outliers``), which is a fence operation
#: by nature and so keeps its own multiplier unless the user picks the IQR method.
DEFAULT_IQR_MULTIPLIER = 3.0

#: 0.75 quantile of the standard normal — makes a MAD-based score comparable to
#: an ordinary z-score.
_MAD_SCALE = 0.6745

#: Detection reaches much further out than cleaning does.
DETECTION_IQR_MULTIPLIER = 15.0
DETECTION_STD_MULTIPLIER = 8.0

#: Fewest non-null values before a cutoff means anything.
MIN_CLEANING_VALUES = 4
MIN_DETECTION_VALUES = 5


#: Characters that survive normalization — everything else is stripped before
#: parsing, so "$400 a person" and "1.5 hours" still read as numbers.
_NON_NUMERIC_RE = r"[^\d\.\-]"


def coerce_numeric_like(value: Any) -> float | None:
    """Parse one possibly-decorated cell as a number, or ``None``.

    Detection scans currency- and unit-laden columns by stripping the decoration
    first, so anything comparing a single cell against those results has to
    strip it the same way — otherwise "$99999" reads as unparseable and a value
    detection flagged is quietly never shown.
    """
    numeric = pd.to_numeric(value, errors="coerce")
    if numeric is not None and not pd.isna(numeric):
        return float(numeric)
    if not isinstance(value, str):
        return None
    stripped = pd.to_numeric(re.sub(_NON_NUMERIC_RE, "", value), errors="coerce")
    return None if pd.isna(stripped) else float(stripped)


def _numeric(values: Any) -> pd.Series:
    """Coerce to a numeric Series, dropping anything unparseable."""
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    return pd.to_numeric(series, errors="coerce").dropna()


def detection_fences(values: Any) -> tuple[float, float] | None:
    """Return the ``(lower, upper)`` cutoffs used to *surface* extreme values.

    Uses a 15× IQR reach either side of the quartiles, falling back to
    mean ± 8×std when the IQR is zero (a column of mostly identical values).
    Returns ``None`` when the column is too small or too flat for a cutoff to
    carry any meaning.
    """
    numeric = _numeric(values)
    if len(numeric) < MIN_DETECTION_VALUES:
        return None

    q25, q75 = numeric.quantile(0.25), numeric.quantile(0.75)
    iqr = q75 - q25
    if iqr > 0:
        reach = DETECTION_IQR_MULTIPLIER * iqr
        return float(q25 - reach), float(q75 + reach)

    mean, std = numeric.mean(), numeric.std()
    if not std > 0:
        return None
    reach = DETECTION_STD_MULTIPLIER * std
    return float(mean - reach), float(mean + reach)


def is_flagged_outlier(value: Any, col_flags: dict[str, Any]) -> bool:
    """True when *value* falls outside the fences detection recorded.

    The preview grid calls this instead of re-deriving a rule of its own, so the
    cells it reddens are exactly the values the profiler flagged. Profiles
    written before the fences were recorded simply highlight nothing.
    """
    lower = col_flags.get("outlier_lower_fence")
    upper = col_flags.get("outlier_upper_fence")
    if lower is None or upper is None:
        return False

    numeric = coerce_numeric_like(value)
    if numeric is None:
        return False
    return bool(numeric < lower or numeric > upper)


@dataclass(frozen=True)
class OutlierPolicy:
    """How outliers are judged, as the user configured it in Settings.

    *threshold* is read against *method*: a modified z-score cutoff for
    ``"mad"``, an IQR multiplier for ``"iqr"``. ``"none"`` turns every outlier
    operation into a no-op — the user asked for their values to be left alone.
    """

    method: OutlierMethod = "mad"
    threshold: float = DEFAULT_THRESHOLD

    @classmethod
    def from_preferences(cls, prefs: Any) -> OutlierPolicy:
        """Build a policy from a UserPreferences model or a preferences dict."""
        if isinstance(prefs, dict):
            method = prefs.get("outlier_method")
            threshold = prefs.get("outlier_threshold")
        else:
            method = getattr(prefs, "outlier_method", None)
            threshold = getattr(prefs, "outlier_threshold", None)

        defaults = cls()
        return cls(
            method=method or defaults.method,
            threshold=defaults.threshold if threshold is None else float(threshold),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize in the preferences shape :meth:`from_preferences` reads.

        One shape both ways keeps the Celery boundary from inventing a second
        vocabulary for the same two values.
        """
        return {"outlier_method": self.method, "outlier_threshold": self.threshold}

    @property
    def enabled(self) -> bool:
        """False when the user turned outlier handling off entirely."""
        return self.method != "none"

    def threshold_for(self, params: dict[str, Any]) -> float:
        """The cutoff for one step — an explicit step param beats the global setting.

        The planner may choose a per-column threshold it can justify from the
        data; that judgement is more specific than the user's default, so it wins.
        """
        explicit = params.get("threshold")
        return self.threshold if explicit is None else float(explicit)

    def iqr_multiplier(self, params: dict[str, Any]) -> float:
        """The IQR reach for row-dropping.

        Honours an explicit step param first, then the user's threshold when
        they picked the IQR method, and otherwise the operation's own default.
        """
        explicit = params.get("threshold")
        if explicit is not None:
            return float(explicit)
        if self.method == "iqr":
            return self.threshold
        return DEFAULT_IQR_MULTIPLIER

    def outlier_mask(self, values: pd.Series, threshold: float | None = None) -> pd.Series:
        """Boolean mask of the values this policy judges extreme, in both tails.

        All-False when the policy is off, or when the column holds too few
        values — or too little spread — for a cutoff to mean anything.
        """
        numeric = pd.to_numeric(values, errors="coerce")
        present = numeric.dropna()
        none_flagged = pd.Series(False, index=values.index)
        if not self.enabled or len(present) < MIN_CLEANING_VALUES:
            return none_flagged

        cutoff = self.threshold if threshold is None else threshold

        if self.method == "iqr":
            q25, q75 = present.quantile(0.25), present.quantile(0.75)
            iqr = q75 - q25
            if iqr <= 0:
                return none_flagged
            reach = cutoff * iqr
            return ((numeric < q25 - reach) | (numeric > q75 + reach)).fillna(False)

        median = present.median()
        mad = (present - median).abs().median()
        if mad == 0:
            # Degenerate spread: the modified z-score is undefined, so fall back
            # to the extreme percentiles at either end.
            low, high = present.quantile(0.01), present.quantile(0.99)
            return ((numeric < low) | (numeric > high)).fillna(False)

        modified_z = _MAD_SCALE * (numeric - median).abs() / mad
        return (modified_z > cutoff).fillna(False)

    def describe(self, threshold: float | None = None) -> str:
        """Short human-readable statement of the cutoff, for audit entries."""
        cutoff = self.threshold if threshold is None else threshold
        if self.method == "iqr":
            return f"outside {cutoff:g}× IQR"
        return f"MAD z-score > {cutoff:g}"
