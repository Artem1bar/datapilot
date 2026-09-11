"""OutlierPolicy is the single source of truth for outlier cutoffs.

Locks the three defects this module was introduced to kill:

  1. ``outlier_method`` / ``outlier_threshold`` were rendered in Settings but
     never read by anything — picking "none" or moving the threshold did
     nothing at all.
  2. Cleaning flagged at MAD z > 5.0 while verification re-checked the same
     step at a hardcoded 3.5, so a step that behaved exactly as configured
     could be reported as failed.
  3. Detection only ever looked at the upper tail, so a suspiciously *low*
     value was never surfaced.

If these start failing, the policy has been bypassed somewhere and the
thresholds are free to drift apart again.
"""

from __future__ import annotations

import pandas as pd

from app.schemas.settings import UserPreferences
from app.services.cleaning import execute_cleaning_plan
from app.services.outliers import DEFAULT_THRESHOLD, OutlierPolicy
from app.services.verification import verify_cleaning_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag(df: pd.DataFrame, column: str, policy: OutlierPolicy | None = None, **params):
    steps = [
        {
            "operation": "flag_extreme_outliers",
            "column": column,
            "params": params,
            "description": "test",
        }
    ]
    return execute_cleaning_plan(df, steps, policy=policy)


def _remove(df: pd.DataFrame, column: str, policy: OutlierPolicy | None = None, **params):
    steps = [
        {
            "operation": "remove_outliers",
            "column": column,
            "params": params,
            "description": "test",
        }
    ]
    return execute_cleaning_plan(df, steps, policy=policy)


# A column whose worst value lands in the old 3.5–5.0 disagreement gap:
# median 14.5, MAD 2.5, max modified z ≈ 4.27. Cleaning (5.0) leaves it alone;
# verification (3.5) used to call that a failure.
_GAP_COLUMN = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 34]


# ---------------------------------------------------------------------------
# Policy construction
# ---------------------------------------------------------------------------


class TestPolicyFromPreferences:
    def test_reads_user_settings(self):
        prefs = UserPreferences(outlier_method="iqr", outlier_threshold=2.0)
        policy = OutlierPolicy.from_preferences(prefs)
        assert policy.method == "iqr"
        assert policy.threshold == 2.0

    def test_accepts_a_plain_dict(self):
        policy = OutlierPolicy.from_preferences({"outlier_method": "none"})
        assert policy.method == "none"

    def test_missing_preferences_fall_back_to_defaults(self):
        policy = OutlierPolicy.from_preferences({})
        assert policy == OutlierPolicy()

    def test_schema_default_matches_pipeline_default(self):
        """The Settings default must be the threshold the pipeline actually uses.

        These drifted before: the schema said 3.5, the cleaner used 5.0.
        """
        assert UserPreferences().outlier_threshold == DEFAULT_THRESHOLD
        assert OutlierPolicy.from_preferences(UserPreferences()) == OutlierPolicy()


# ---------------------------------------------------------------------------
# The policy actually reaches the cleaning operations
# ---------------------------------------------------------------------------


class TestPolicyDrivesCleaning:
    def test_method_none_disables_flagging(self):
        df = pd.DataFrame({"amount": [10, 10, 10, 10, 10, 10, 99999]})
        cleaned, audit, _ = _flag(df, "amount", policy=OutlierPolicy(method="none"))
        assert cleaned["amount"].notna().all(), "method='none' must not null any value"
        assert audit == []
        assert "_flagged" not in cleaned.columns

    def test_method_none_disables_row_removal(self):
        df = pd.DataFrame({"amount": [10.0, 20.0, 30.0, 40.0, 50.0, 9999.0]})
        cleaned, audit, _ = _remove(df, "amount", policy=OutlierPolicy(method="none"))
        assert len(cleaned) == len(df), "method='none' must not drop rows"
        assert audit == []

    def test_tighter_threshold_flags_more(self):
        """The same data, judged by two thresholds, must give different answers."""
        df = pd.DataFrame({"amount": _GAP_COLUMN})
        forgiving, _, _ = _flag(df, "amount", policy=OutlierPolicy(threshold=5.0))
        strict, _, _ = _flag(df, "amount", policy=OutlierPolicy(threshold=3.0))
        assert forgiving["amount"].notna().all(), "z≈4.27 is inside a 5.0 cutoff"
        assert strict["amount"].isna().any(), "z≈4.27 is outside a 3.0 cutoff"

    def test_iqr_method_uses_threshold_as_multiplier(self):
        # q25=20, q75=40, IQR=20 → a 1.5× fence sits at 70, a 6× fence at 160.
        data = [10.0, 20.0, 30.0, 40.0, 50.0] * 4 + [100.0]
        tight, _, _ = _flag(
            pd.DataFrame({"v": data}), "v", policy=OutlierPolicy(method="iqr", threshold=1.5)
        )
        loose, _, _ = _flag(
            pd.DataFrame({"v": data}), "v", policy=OutlierPolicy(method="iqr", threshold=6.0)
        )
        assert tight["v"].isna().any(), "100 is beyond a 1.5× IQR fence"
        assert loose["v"].notna().all(), "100 is inside a 6× IQR fence"

    def test_explicit_step_params_still_win(self):
        """A planner-chosen per-column threshold overrides the user's global one."""
        df = pd.DataFrame({"amount": _GAP_COLUMN})
        cleaned, _, _ = _flag(df, "amount", policy=OutlierPolicy(threshold=5.0), threshold=3.0)
        assert cleaned["amount"].isna().any()

    def test_omitting_the_policy_keeps_the_documented_default(self):
        """Callers that pass no policy behave exactly as before."""
        df = pd.DataFrame({"amount": _GAP_COLUMN})
        cleaned, _, _ = _flag(df, "amount")
        assert cleaned["amount"].notna().all(), "default cutoff is the forgiving 5.0"


# ---------------------------------------------------------------------------
# Both tails
# ---------------------------------------------------------------------------


class TestBothTails:
    def test_low_outlier_is_flagged(self):
        df = pd.DataFrame({"price": [1000, 1010, 1020, 1030, 1040, 1050, 1]})
        cleaned, audit, _ = _flag(df, "price")
        assert pd.isna(cleaned["price"].iloc[-1]), "a suspiciously low value must be flagged"
        assert any(e["operation"] == "flag_extreme_outliers" for e in audit)

    def test_low_outlier_row_is_removed(self):
        df = pd.DataFrame({"amount": [100.0, 105.0, 110.0, 115.0, 120.0, -900.0]})
        cleaned, _, _ = _remove(df, "amount")
        assert -900.0 not in cleaned["amount"].values


# ---------------------------------------------------------------------------
# Verification agrees with cleaning
# ---------------------------------------------------------------------------


class TestVerificationAgreesWithCleaning:
    def test_no_failure_when_the_cleaner_correctly_flagged_nothing(self):
        """The 3.5-vs-5.0 mismatch bug.

        With a 5.0 cutoff the cleaner correctly flags nothing, so no ``_flagged``
        column is created. Verification then re-checked at 3.5, saw the z≈4.27
        value as an outlier, and marked the step failed.
        """
        policy = OutlierPolicy(threshold=5.0)
        df = pd.DataFrame({"amount": _GAP_COLUMN})
        steps = [
            {
                "operation": "flag_extreme_outliers",
                "column": "amount",
                "params": {},
                "description": "flag outliers",
            }
        ]
        cleaned, audit, failed = execute_cleaning_plan(df.copy(), steps, policy=policy)
        assert cleaned["amount"].notna().all(), "precondition: nothing should be flagged"

        report = verify_cleaning_result(
            original_df=df,
            cleaned_df=cleaned,
            steps=steps,
            audit_log=audit,
            original_quality_flags={},
            failed_steps=failed,
            policy=policy,
        )
        outlier_steps = [s for s in report.step_results if s.operation == "flag_extreme_outliers"]
        assert outlier_steps, "the step should have been verified"
        assert all(s.passed for s in outlier_steps), (
            "verification must use the same cutoff the cleaner used; "
            f"got: {[(s.expected, s.actual) for s in outlier_steps]}"
        )

    def test_still_fails_when_a_real_outlier_was_left_behind(self):
        """The alignment fix must not turn verification into a rubber stamp."""
        policy = OutlierPolicy(threshold=5.0)
        df = pd.DataFrame({"amount": [50, 80, 90, 100, 110, 120, 150, 180, 200, 99999]})
        steps = [
            {
                "operation": "flag_extreme_outliers",
                "column": "amount",
                "params": {},
                "description": "flag outliers",
            }
        ]
        report = verify_cleaning_result(
            original_df=df,
            cleaned_df=df.copy(),  # pretend the step never ran
            steps=steps,
            audit_log=[],
            original_quality_flags={},
            failed_steps=[],
            policy=policy,
        )
        outlier_steps = [s for s in report.step_results if s.operation == "flag_extreme_outliers"]
        assert outlier_steps and not outlier_steps[0].passed
