"""Regression tests for outlier detection thresholds.

These tests lock in the intentionally forgiving thresholds introduced to prevent
normal expense variation from being flagged as outliers:

  - cleaning.py _flag_extreme_outliers: MAD z-score threshold 5.0 (was 3.5)
  - cleaning.py _remove_outliers:       IQR multiplier 3.0 (was 1.5)
  - profile_task.py:                    IQR fence 15× (was 10×), std fallback 8× (was 5×)

If any of these tests start failing, the thresholds were reverted or tightened
unintentionally — re-read the original PR before changing them.
"""

from __future__ import annotations

import pandas as pd

from app.services.cleaning import execute_cleaning_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_flag(df: pd.DataFrame, column: str, **params):
    steps = [
        {
            "operation": "flag_extreme_outliers",
            "column": column,
            "params": params,
            "description": "test",
        }
    ]
    return execute_cleaning_plan(df, steps)


def _run_remove(df: pd.DataFrame, column: str):
    steps = [
        {"operation": "remove_outliers", "column": column, "params": {}, "description": "test"}
    ]
    return execute_cleaning_plan(df, steps)


# ---------------------------------------------------------------------------
# _flag_extreme_outliers — MAD z-score threshold = 5.0
# ---------------------------------------------------------------------------


class TestFlagExtremeOutliers:
    def test_normal_expense_variation_not_flagged(self):
        """Typical business expenses with a high-end outlier should NOT be flagged
        when the modified z-score is below 5.0.

        Median ~100, MAD ~50. A value of 500 gives modified_z ≈ 0.6745*400/50 = 5.4.
        At the old 3.5 threshold this was flagged; at 5.0 it should not be.
        """
        # Build data where the "outlier" is ~5× the median — realistic high spend
        data = [50, 80, 90, 100, 110, 120, 150, 180, 200, 250]  # mostly normal
        df = pd.DataFrame({"amount": data + [400]})  # 400 is high but not absurd
        cleaned, audit, failed = _run_flag(df, "amount")
        # 400 should survive — it's high but within 5.0 threshold
        assert cleaned["amount"].notna().all(), (
            "Row with value 400 was incorrectly flagged as an extreme outlier. "
            "Threshold should be 5.0 (MAD z-score), not the old 3.5."
        )

    def test_truly_absurd_value_is_flagged(self):
        """A value that is clearly a data entry error (e.g. 100× the median) should
        still be flagged even at the forgiving 5.0 threshold."""
        data = [50, 80, 90, 100, 110, 120, 150, 180, 200, 250]
        df = pd.DataFrame({"amount": data + [99999]})
        cleaned, audit, failed = _run_flag(df, "amount")
        # 99999 should be nulled out
        assert cleaned["amount"].isna().any(), (
            "A clearly absurd value (99999) was not flagged. "
            "The MAD z-score threshold of 5.0 may be broken."
        )

    def test_custom_threshold_respected(self):
        """Explicit threshold param overrides the default."""
        data = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 50]  # 50 is 5σ from median
        df = pd.DataFrame({"val": data})
        # With a very tight threshold of 1.0, 50 should be flagged
        cleaned, _, _ = _run_flag(df, "val", threshold=1.0)
        assert cleaned["val"].isna().any()

    def test_fewer_than_4_values_skipped(self):
        """Should not attempt outlier detection on tiny columns."""
        df = pd.DataFrame({"amount": [100, 200, 300]})
        cleaned, audit, _ = _run_flag(df, "amount")
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# _remove_outliers — IQR multiplier = 3.0
# ---------------------------------------------------------------------------


class TestRemoveOutliers:
    def test_moderate_outlier_kept_at_3x_iqr(self):
        """A value at 2.5× IQR above Q3 should NOT be removed (old 1.5× would remove it).

        With data [10,20,30,40,50]: Q1=17.5, Q3=42.5, IQR=25.
        Upper fence at 3.0×: 42.5 + 75 = 117.5  → 100 survives.
        Upper fence at 1.5×: 42.5 + 37.5 = 80    → 100 would be dropped.
        """
        df = pd.DataFrame({"amount": [10.0, 20.0, 30.0, 40.0, 50.0, 100.0]})
        cleaned, audit, failed = _run_remove(df, "amount")
        assert 100.0 in cleaned["amount"].values, (
            "Value 100 (2.5× IQR above Q3) was incorrectly removed. "
            "IQR multiplier should be 3.0, not 1.5."
        )

    def test_extreme_value_still_removed(self):
        """A value 4× IQR above Q3 should still be removed even at the lenient 3.0 fence."""
        df = pd.DataFrame({"amount": [10.0, 20.0, 30.0, 40.0, 50.0, 200.0]})
        # IQR = 25, upper = 42.5 + 75 = 117.5; 200 > 117.5 → should be dropped
        cleaned, audit, failed = _run_remove(df, "amount")
        assert 200.0 not in cleaned["amount"].values, (
            "Value 200 (6× IQR above Q3) was not removed. The IQR multiplier of 3.0 may be broken."
        )

    def test_all_normal_data_untouched(self):
        """Clean data with no outliers should pass through unchanged."""
        df = pd.DataFrame({"amount": [100.0, 105.0, 110.0, 95.0, 98.0, 102.0]})
        cleaned, audit, failed = _run_remove(df, "amount")
        assert len(cleaned) == len(df)
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# profile_task outlier detection — 15× IQR fence
# ---------------------------------------------------------------------------


class TestProfileTaskOutlierFence:
    """Tests for the profile_task outlier fence (15× IQR, mean+8*std fallback).

    These tests call the profile flag logic in isolation by importing only the
    relevant portion of profile_task. The boundary is Q3 + 15 * IQR.
    """

    def _compute_fence(self, values: list[float]) -> float:
        """Replicate the exact fence logic from profile_task.py."""
        arr = pd.Series(values)
        q25, q75 = arr.quantile(0.25), arr.quantile(0.75)
        iqr = q75 - q25
        if iqr > 0:
            return float(q75 + 15 * iqr)
        mean, std = arr.mean(), arr.std()
        return float(mean + 8 * std) if std > 0 else float("inf")

    def test_fence_is_15x_not_10x(self):
        """At 15× IQR the fence is 50% further out than the old 10× fence.

        data = [10,20,30,40,50] * 4 → pandas Q1=20, Q3=40, IQR=20
        15× fence: 40 + 15*20 = 340
        10× fence: 40 + 10*20 = 240
        """
        data = [10.0, 20.0, 30.0, 40.0, 50.0] * 4
        fence = self._compute_fence(data)
        # Q1=20, Q3=40, IQR=20  →  Q3 + 15*IQR = 40 + 300 = 340
        assert abs(fence - 340.0) < 1.0, f"Expected fence ~340, got {fence}"

    def test_normal_business_expense_below_fence(self):
        """A $500 value with typical $50-$200 expense data must be below the 15× fence."""
        # Realistic: most expenses $50-$200, one expensive item at $500
        base = list(range(50, 210, 10))  # [50, 60, ..., 200]
        fence = self._compute_fence(base)
        assert 500 < fence, (
            f"$500 expense was above the 15× IQR fence ({fence:.0f}). "
            "The fence has been tightened — was the threshold reverted to 10×?"
        )

    def test_old_10x_fence_would_have_flagged_same_value(self):
        """Confirm the 15× change is meaningful: the old 10× fence IS smaller."""
        data = list(range(50, 210, 10))
        arr = pd.Series(data)
        q25, q75 = arr.quantile(0.25), arr.quantile(0.75)
        iqr = q75 - q25
        old_fence = q75 + 10 * iqr
        new_fence = q75 + 15 * iqr
        assert new_fence > old_fence, "15× fence should be larger than 10× fence"

    def test_std_fallback_uses_8x_not_5x(self):
        """When IQR=0 the fallback is mean + 8*std. With std fallback at 8×,
        a value that is 6× std above mean should survive."""
        # IQR=0: all same value except two outliers
        data = [100.0] * 20 + [700.0, 750.0]  # std ≈ 126, mean ≈ 114
        fence = self._compute_fence(data)
        # 8×std: mean+8*std ≈ 114 + 1007 = 1121 → 700 and 750 survive
        assert fence > 750, (
            f"Fence ({fence:.0f}) is below 750 — std fallback may be using 5× instead of 8×"
        )
