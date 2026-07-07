"""Tests for domain detection and domain-gated quality heuristics.

Survey/expense heuristics used to run on every dataset; they now only fire for
the detected-or-declared "survey" domain, so a generic business CSV is profiled
without survey-specific flags.
"""

from __future__ import annotations

import pandas as pd

from app.tasks.profile_task import detect_domain, detect_quality_issues


def test_detect_domain_survey_by_marker_columns():
    df = pd.DataFrame({"ResponseId": ["R_1"], "Progress": [100], "Finished": [True], "q1": [1]})
    assert detect_domain(df) == "survey"


def test_single_marker_column_is_not_survey():
    # A lone coincidental "Progress" column must not promote to survey.
    df = pd.DataFrame({"Progress": [10, 20], "widget": ["a", "b"]})
    assert detect_domain(df) is None


def test_detect_domain_generic_for_business_csv():
    df = pd.DataFrame({"order_id": [1, 2], "city": ["Denver", "Austin"], "sales": [99.0, 40.0]})
    assert detect_domain(df) is None


def test_non_survey_csv_has_no_survey_flags():
    # First row has a long string and there's a coincidental Progress column, but
    # this is not a survey → no qualtrics_header_row and no _incomplete_responses.
    df = pd.DataFrame(
        {
            "description": ["x" * 60, "short", "also short"],
            "Progress": [50, 100, 80],
            "sales": [10, 20, 30],
        }
    )
    flags = detect_quality_issues(df)
    assert "qualtrics_header_row" not in flags
    assert "_incomplete_responses" not in flags


def test_survey_dataset_flags_incomplete_responses():
    df = pd.DataFrame(
        {
            "ResponseId": ["R_1", "R_2", "R_3"],
            "StartDate": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "Progress": [100, 40, 100],
            "Finished": ["True", "False", "True"],
        }
    )
    flags = detect_quality_issues(df)  # auto-detected survey (3 marker columns)
    assert "_incomplete_responses" in flags
    assert flags["_incomplete_responses"]["count"] == 1


def test_explicit_domain_overrides_autodetection():
    # Force generic on data that would auto-detect as survey.
    df = pd.DataFrame({"ResponseId": ["R_1"], "Progress": [40], "Finished": ["False"]})
    flags = detect_quality_issues(df, domain="generic")
    assert "_incomplete_responses" not in flags
