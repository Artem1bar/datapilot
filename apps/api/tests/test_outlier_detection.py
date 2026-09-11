"""Profiler outlier detection covers both tails, and the grid reuses its fences.

Two defects locked here:

  1. Detection only tested ``value > q75 + 15*IQR``, so a suspiciously *low*
     value — a negative amount, a 1 among thousands — was never surfaced.
  2. The preview grid re-derived its own cruder rule (``value > q75 * 3``)
     instead of reusing what the profiler decided, so the cells painted red
     were not the values the profiler had flagged. That rule also misfired
     entirely on columns whose q75 was zero or negative.

The grid and the profiler now share :func:`detection_fences`, so they cannot
disagree.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.outliers import (
    DETECTION_IQR_MULTIPLIER,
    detection_fences,
    is_flagged_outlier,
)
from app.tasks.profile_task import detect_quality_issues

# ---------------------------------------------------------------------------
# Fences
# ---------------------------------------------------------------------------


class TestDetectionFences:
    def test_upper_fence_is_15x_iqr(self):
        """data → q25=20, q75=40, IQR=20 → upper = 40 + 15*20 = 340."""
        values = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0] * 4)
        lower, upper = detection_fences(values)
        assert upper == pytest.approx(340.0)
        assert DETECTION_IQR_MULTIPLIER == 15.0

    def test_lower_fence_mirrors_the_upper_one(self):
        """The same 15× reach below q25: 20 - 15*20 = -280."""
        values = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0] * 4)
        lower, upper = detection_fences(values)
        assert lower == pytest.approx(-280.0)

    def test_std_fallback_when_iqr_is_zero(self):
        """IQR=0 (mostly identical values) falls back to mean ± 8*std."""
        values = pd.Series([100.0] * 20 + [700.0, 750.0])
        lower, upper = detection_fences(values)
        mean, std = values.mean(), values.std()
        assert upper == pytest.approx(mean + 8 * std)
        assert lower == pytest.approx(mean - 8 * std)

    def test_no_fence_when_there_are_too_few_values(self):
        assert detection_fences(pd.Series([1.0, 2.0, 3.0])) is None

    def test_no_fence_when_every_value_is_identical(self):
        """Zero IQR and zero spread — nothing can be called extreme."""
        assert detection_fences(pd.Series([5.0] * 10)) is None


# ---------------------------------------------------------------------------
# The profiler flags both tails
# ---------------------------------------------------------------------------


class TestProfilerBothTails:
    def test_flags_a_high_outlier(self):
        df = pd.DataFrame({"amount": [100.0, 110.0, 120.0, 130.0, 140.0, 99999.0]})
        flags = detect_quality_issues(df, domain="generic")
        assert flags["amount"]["has_extreme_outliers"] is True
        assert 99999.0 in flags["amount"]["extreme_values"]

    def test_flags_a_low_outlier(self):
        """A price of 1 among four-figure prices is as wrong as a 99999."""
        df = pd.DataFrame({"price": [4000.0, 4100.0, 4200.0, 4300.0, 4400.0, 1.0]})
        flags = detect_quality_issues(df, domain="generic")
        assert flags.get("price", {}).get("has_extreme_outliers") is True, (
            "a suspiciously low value must be detected — detection was upper-tail only"
        )
        assert 1.0 in flags["price"]["extreme_values"]

    def test_records_both_fences_for_the_grid(self):
        df = pd.DataFrame({"amount": [100.0, 110.0, 120.0, 130.0, 140.0, 99999.0]})
        col_flags = detect_quality_issues(df, domain="generic")["amount"]
        assert "outlier_lower_fence" in col_flags
        assert "outlier_upper_fence" in col_flags
        assert col_flags["outlier_lower_fence"] < col_flags["outlier_upper_fence"]

    def test_clean_data_is_not_flagged(self):
        df = pd.DataFrame({"amount": [100.0, 105.0, 110.0, 115.0, 120.0, 125.0]})
        flags = detect_quality_issues(df, domain="generic")
        assert not flags.get("amount", {}).get("has_extreme_outliers")


# ---------------------------------------------------------------------------
# The grid highlights exactly what the profiler flagged
# ---------------------------------------------------------------------------


class TestGridAgreesWithProfiler:
    def test_does_not_paint_values_the_profiler_accepted(self):
        """The old ``> q75 * 3`` rule reddened cells the profiler never flagged.

        With expenses of 50–200: q75=162.5, IQR=75, so the profiler's fence is
        1287.5. The old grid rule fired at 487.5, so a legitimate 600 was shown
        as an error.
        """
        values = pd.Series([float(v) for v in range(50, 210, 10)])
        _lower, upper = detection_fences(values)
        col_flags = {
            "has_extreme_outliers": True,
            "outlier_lower_fence": _lower,
            "outlier_upper_fence": upper,
        }
        assert 600.0 < upper, "precondition: the profiler accepts 600"
        assert 600.0 > values.quantile(0.75) * 3, "precondition: the old rule rejected it"
        assert is_flagged_outlier(600.0, col_flags) is False

    def test_paints_values_beyond_either_fence(self):
        col_flags = {
            "has_extreme_outliers": True,
            "outlier_lower_fence": 0.0,
            "outlier_upper_fence": 1000.0,
        }
        assert is_flagged_outlier(5000.0, col_flags) is True
        assert is_flagged_outlier(-1.0, col_flags) is True
        assert is_flagged_outlier(500.0, col_flags) is False

    def test_negative_column_does_not_paint_every_cell(self):
        """``q75 * 3`` on a negative q75 marked the whole column as outliers."""
        values = pd.Series([-100.0, -95.0, -90.0, -85.0, -80.0, -75.0])
        fences = detection_fences(values)
        assert fences is not None
        lower, upper = fences
        col_flags = {
            "has_extreme_outliers": True,
            "outlier_lower_fence": lower,
            "outlier_upper_fence": upper,
        }
        assert values.quantile(0.75) * 3 < values.min(), "precondition: the old rule caught all"
        assert not any(is_flagged_outlier(v, col_flags) for v in values)

    def test_no_fences_means_nothing_is_painted(self):
        """Profiles written before fences were recorded must not crash the grid."""
        assert is_flagged_outlier(99999.0, {"has_extreme_outliers": True}) is False
        assert is_flagged_outlier(99999.0, {}) is False

    def test_non_numeric_values_are_never_painted(self):
        col_flags = {
            "has_extreme_outliers": True,
            "outlier_lower_fence": 0.0,
            "outlier_upper_fence": 10.0,
        }
        assert is_flagged_outlier("n/a", col_flags) is False
        assert is_flagged_outlier(None, col_flags) is False

    def test_decorated_numbers_are_read_the_way_detection_read_them(self):
        """Detection strips currency and units before parsing, so the grid must too.

        Otherwise the profiler flags "$99999" and the grid, seeing an
        unparseable string, quietly never highlights it.
        """
        col_flags = {
            "has_extreme_outliers": True,
            "outlier_lower_fence": 0.0,
            "outlier_upper_fence": 1000.0,
        }
        assert is_flagged_outlier("$99999", col_flags) is True
        assert is_flagged_outlier("400 a person", col_flags) is False

    def test_a_currency_column_highlights_the_value_the_profiler_flagged(self):
        """End to end: what detect_quality_issues flags is what the grid paints."""
        df = pd.DataFrame({"cost": ["$100", "$110", "$120", "$130", "$140", "$99999"]})
        col_flags = detect_quality_issues(df, domain="survey")["cost"]
        assert col_flags["has_extreme_outliers"] is True
        assert is_flagged_outlier("$99999", col_flags) is True
        assert is_flagged_outlier("$100", col_flags) is False
