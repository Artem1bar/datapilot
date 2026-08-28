"""The dataset briefing — the facts the planner needs before it picks a test.

The validator can reject a spec that is malformed or names a column that does
not exist. It cannot reject one that is well-formed and statistically
inappropriate: an unweighted mean on a survey that shipped a weight column, an
independent test on data that repeats each respondent twice, a Pearson
correlation on a variable with a skewness of 4. Those choices are made before
validation, from whatever the planner was told about the dataset.

These tests pin what it is told. They assert on the structured briefing rather
than on prose, so the rendered wording stays tunable — except for two cases at
the end, where the point *is* that a specific fact survives into the text.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pytest

from app.services.analysis_briefing import (
    MAX_BRIEFING_CHARS,
    MAX_SCANNED_COLUMNS,
    MIN_TREND_POINTS,
    SCAN_SAMPLE_ROWS,
    DatasetBriefing,
    briefing_text,
    build_briefing,
    render_briefing,
)

# The timing budget asserted below, in CPU seconds. CPU rather than wall clock
# because the budget is a property of the work the briefing does, and a wall
# clock on a loaded build machine measures the other jobs on it. Generous
# against the measured cost (see the analysis_briefing module docstring): the
# test is here to catch a briefing that starts scanning whole columns, not to
# rank machines.
BUDGET_CPU_SECONDS = 1.0


def _named(items, column: str):
    """The single briefing entry for *column*, or None."""
    matches = [item for item in items if item.column == column]
    assert len(matches) <= 1, f"{column!r} reported {len(matches)} times"
    return matches[0] if matches else None


@pytest.fixture
def survey() -> pd.DataFrame:
    """A survey-shaped frame: weights, an id, Likert items, thin group levels."""
    rng = np.random.default_rng(7)
    n = 300
    return pd.DataFrame(
        {
            "respondent_id": [f"R{i:04d}" for i in range(n)],
            # Design weights: strictly positive, fractional, averaging one.
            "weight_final": np.round(rng.uniform(0.4, 1.6, n) / 0.9926, 4),
            # Same name pattern, impossible values — must not be offered.
            "weight_delta": rng.uniform(-2.0, 2.0, n),
            "income": np.round(rng.lognormal(10.0, 1.2, n), 2),
            "symmetric_score": rng.normal(50.0, 8.0, n),
            "visits": rng.poisson(1.2, n),
            "q1_agree": rng.integers(1, 6, n),
            "survey_year": rng.integers(2015, 2025, n),
            "exam_score": rng.integers(1, 101, n),
            "region": ["North"] * 100 + ["South"] * 100 + ["East"] * 100,
            "arm": ["control"] * 149 + ["treatment"] * 149 + ["pilot"] * 2,
        }
    )


class TestWeightDetection:
    def test_genuine_weight_column_is_offered(self, survey: pd.DataFrame):
        briefing = build_briefing(survey)
        weight = _named(briefing.weights, "weight_final")
        assert weight is not None
        assert weight.confidence == "high"
        assert weight.minimum > 0
        assert weight.mean == pytest.approx(1.0, abs=0.15)

    def test_negative_values_disqualify_a_weight_named_column(self, survey: pd.DataFrame):
        # A weight of -0.4 is not a weight, whatever the column is called.
        assert _named(build_briefing(survey).weights, "weight_delta") is None

    def test_plain_numeric_columns_are_not_offered(self, survey: pd.DataFrame):
        briefing = build_briefing(survey)
        assert _named(briefing.weights, "income") is None
        assert _named(briefing.weights, "symmetric_score") is None

    def test_population_scale_weights_are_offered(self):
        # Expansion weights sum to a population rather than to n.
        frame = pd.DataFrame({"pweight": np.linspace(820.5, 1180.25, 200)})
        weight = _named(build_briefing(frame).weights, "pweight")
        assert weight is not None
        assert weight.confidence in ("high", "moderate")
        assert weight.total == pytest.approx(float(frame["pweight"].sum()), rel=1e-6)

    def test_body_weight_is_reported_but_not_confidently(self):
        # `weight_kg` in a health file is the commonest false positive there is.
        frame = pd.DataFrame({"weight_kg": np.arange(48, 108, dtype=float)})
        weight = _named(build_briefing(frame).weights, "weight_kg")
        assert weight is not None
        assert weight.confidence == "low"
        assert "kg" in weight.reason or "integer" in weight.reason

    def test_no_candidate_is_recorded_when_nothing_matches(self):
        frame = pd.DataFrame({"revenue": [1.0, 2.0, 3.0]})
        assert build_briefing(frame).weights == ()


class TestRepetitionStructure:
    def test_long_format_repetition_is_reported(self):
        frame = pd.DataFrame(
            {
                "respondent_id": [f"R{i:03d}" for i in range(300)] * 2,
                "wave": ["pre"] * 300 + ["post"] * 300,
                "score": np.arange(600, dtype=float),
            }
        )
        key = _named(build_briefing(frame).keys, "respondent_id")
        assert key is not None
        assert key.distinct == 300
        assert key.rows == 600
        assert key.row_unique is False
        assert key.max_rows_per_value == 2
        assert key.uniform_repeat is True

    def test_row_unique_key_is_reported_as_unique(self, survey: pd.DataFrame):
        key = _named(build_briefing(survey).keys, "respondent_id")
        assert key is not None
        assert key.row_unique is True
        assert key.distinct == len(survey)
        assert key.max_rows_per_value == 1

    def test_identifier_values_are_never_reported(self):
        frame = pd.DataFrame({"patient_id": ["MRN-00042", "MRN-00043", "MRN-00044"]})
        text = render_briefing(build_briefing(frame))
        assert "patient_id" in text
        assert "MRN-00042" not in text


class TestDistributionShape:
    def test_skewed_and_symmetric_columns_are_distinguished(self, survey: pd.DataFrame):
        briefing = build_briefing(survey)
        income = _named(briefing.numeric, "income")
        symmetric = _named(briefing.numeric, "symmetric_score")
        assert income is not None and symmetric is not None
        assert income.skewness > 2.0
        assert income.shape == "highly skewed"
        assert abs(symmetric.skewness) < 0.5
        assert symmetric.shape == "symmetric"

    def test_count_like_columns_are_distinguished_from_continuous(self, survey: pd.DataFrame):
        briefing = build_briefing(survey)
        assert _named(briefing.numeric, "visits").kind == "count"
        assert _named(briefing.numeric, "income").kind == "continuous"

    def test_zero_share_is_reported(self):
        frame = pd.DataFrame({"spend": [0.0] * 30 + [5.0, 7.0, 9.0, 11.0, 13.0] * 2})
        column = _named(build_briefing(frame).numeric, "spend")
        assert column.zero_share == pytest.approx(0.75, abs=0.01)

    def test_excess_kurtosis_is_reported_for_a_heavy_tail(self):
        rng = np.random.default_rng(3)
        frame = pd.DataFrame({"heavy": rng.standard_t(3, 4000)})
        column = _named(build_briefing(frame).numeric, "heavy")
        assert column.excess_kurtosis > 1.0

    def test_binary_column_is_labelled_binary(self):
        frame = pd.DataFrame({"converted": [0, 1] * 40})
        assert _named(build_briefing(frame).numeric, "converted").kind == "binary"


class TestGroupingStructure:
    def test_minimum_group_size_is_reported(self, survey: pd.DataFrame):
        group = _named(build_briefing(survey).groups, "arm")
        assert group is not None
        assert group.levels == 3
        assert group.min_group_size == 2
        assert group.max_group_size == 149
        assert group.smallest_level == "pilot"

    def test_balanced_grouping_column_is_reported(self, survey: pd.DataFrame):
        group = _named(build_briefing(survey).groups, "region")
        assert group.levels == 3
        assert group.min_group_size == 100

    def test_high_cardinality_columns_are_not_grouping_columns(self, survey: pd.DataFrame):
        assert _named(build_briefing(survey).groups, "respondent_id") is None


class TestDateColumns:
    def test_three_distinct_dates_are_too_sparse_for_a_trend(self):
        frame = pd.DataFrame(
            {
                "measured_at": pd.to_datetime(["2024-01-01", "2024-06-01", "2024-12-01"] * 20),
                "value": np.arange(60, dtype=float),
            }
        )
        date = _named(build_briefing(frame).dates, "measured_at")
        assert date is not None
        assert date.distinct == 3
        assert date.distinct < MIN_TREND_POINTS
        assert date.too_sparse_for_trend is True

    def test_a_daily_series_reports_its_range_and_regular_spacing(self):
        frame = pd.DataFrame({"day": pd.date_range("2023-01-01", periods=400, freq="D")})
        date = _named(build_briefing(frame).dates, "day")
        assert date.distinct == 400
        assert date.start.startswith("2023-01-01")
        assert date.end.startswith("2024-02-04")
        assert date.median_gap_days == pytest.approx(1.0)
        assert date.regular is True
        assert date.too_sparse_for_trend is False

    def test_irregular_spacing_is_reported_as_irregular(self):
        days = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-02-20", "2024-02-21"] * 3)
        date = _named(build_briefing(pd.DataFrame({"seen": days})).dates, "seen")
        assert date.regular is False


class TestOrdinalDetection:
    def test_one_to_five_integer_column_is_likert_shaped(self, survey: pd.DataFrame):
        item = _named(build_briefing(survey).ordinal, "q1_agree")
        assert item is not None
        assert item.kind == "integer_scale"
        assert (item.minimum, item.maximum) == (1, 5)
        assert item.levels == 5

    def test_a_year_column_is_not_likert(self, survey: pd.DataFrame):
        assert _named(build_briefing(survey).ordinal, "survey_year") is None

    def test_a_score_out_of_a_hundred_is_not_likert(self, survey: pd.DataFrame):
        assert _named(build_briefing(survey).ordinal, "exam_score") is None

    def test_agreement_labels_are_detected(self):
        labels = ["Strongly agree", "Agree", "Neutral", "Disagree", "Strongly disagree"]
        frame = pd.DataFrame({"q7": labels * 12})
        item = _named(build_briefing(frame).ordinal, "q7")
        assert item is not None
        assert item.kind == "labelled"
        assert item.levels == 5

    def test_ordinary_categories_are_not_ordinal(self):
        frame = pd.DataFrame({"region": ["North", "South", "East", "West"] * 10})
        assert _named(build_briefing(frame).ordinal, "region") is None


class TestMissingness:
    def test_per_column_rates_are_reported(self):
        frame = pd.DataFrame({"a": [1.0, None, 3.0, 4.0], "b": [1.0, 2.0, 3.0, 4.0]})
        missing = build_briefing(frame).missingness
        assert _named(missing.columns, "a").rate == pytest.approx(0.25)
        assert _named(missing.columns, "b") is None

    def test_concentrated_missingness_is_distinguished_from_scattered(self):
        # Ten rows are missing four fields each; nothing else is missing.
        rows = 100
        frame = pd.DataFrame({f"q{i}": np.arange(rows, dtype=float) for i in range(4)})
        frame.iloc[:10] = np.nan
        missing = build_briefing(frame).missingness
        assert missing.incomplete_row_share == pytest.approx(0.10)
        assert missing.mean_missing_fields_in_incomplete_rows == pytest.approx(4.0)

    def test_a_complete_frame_reports_no_missingness(self):
        frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        missing = build_briefing(frame).missingness
        assert missing.columns == ()
        assert missing.incomplete_row_share == 0.0


class TestLowInformationColumns:
    def test_a_constant_column_is_flagged(self):
        frame = pd.DataFrame({"export_version": ["v3"] * 50, "value": np.arange(50.0)})
        flagged = _named(build_briefing(frame).low_information, "export_version")
        assert flagged is not None
        assert flagged.reason == "near-constant"

    def test_free_text_is_flagged_as_high_cardinality(self):
        frame = pd.DataFrame({"comment": [f"free text {i}" for i in range(200)]})
        flagged = _named(build_briefing(frame).low_information, "comment")
        assert flagged is not None
        assert flagged.reason == "high-cardinality"


class TestBounds:
    def test_a_two_hundred_column_frame_stays_bounded(self):
        rng = np.random.default_rng(11)
        frame = pd.DataFrame({f"q{i:03d}": rng.integers(1, 6, 400) for i in range(200)})
        briefing = build_briefing(frame)
        text = render_briefing(briefing)

        assert briefing.columns == 200
        assert briefing.columns_not_scanned == 200 - MAX_SCANNED_COLUMNS
        assert len(briefing.ordinal) <= 8
        assert briefing.ordinal_omitted > 0
        assert len(text) <= MAX_BRIEFING_CHARS
        assert "more" in text

    def test_a_typical_frame_renders_compactly(self, survey: pd.DataFrame):
        # A few hundred tokens. Four characters per token is the usual rule of
        # thumb, so 1,800 characters is roughly a 450-token ceiling.
        assert len(render_briefing(build_briefing(survey))) < 1_800

    def test_large_frames_are_sampled_for_distribution_statistics(self):
        rng = np.random.default_rng(5)
        rows = SCAN_SAMPLE_ROWS * 2
        frame = pd.DataFrame({"x": rng.normal(size=rows), "g": ["a", "b"] * (rows // 2)})
        briefing = build_briefing(frame)
        assert briefing.rows == rows
        assert briefing.sampled_rows == SCAN_SAMPLE_ROWS
        # Counts stay exact even when the distribution statistics are sampled.
        assert _named(briefing.groups, "g").min_group_size == rows // 2

    def test_the_briefing_fits_the_budget(self):
        rng = np.random.default_rng(13)
        rows = 200_000
        frame = pd.DataFrame(
            {
                **{f"n{i}": rng.normal(size=rows) for i in range(10)},
                **{f"q{i}": rng.integers(1, 6, rows) for i in range(20)},
                **{f"c{i}": rng.choice(["a", "b", "c", "d"], rows) for i in range(8)},
                "respondent_id": np.arange(rows),
                "weight_final": rng.uniform(0.5, 1.5, rows),
            }
        )
        briefing_text(frame.head(50))  # warm the import-time lazy paths
        start = time.process_time()
        text = briefing_text(frame)
        elapsed = time.process_time() - start
        assert text
        assert elapsed < BUDGET_CPU_SECONDS, f"briefing took {elapsed:.3f}s of CPU"


class TestEdgeCases:
    def test_an_empty_frame_does_not_raise(self):
        briefing = build_briefing(pd.DataFrame())
        assert briefing.rows == 0
        assert briefing.columns == 0
        assert isinstance(render_briefing(briefing), str)

    def test_a_single_row_frame_does_not_raise(self):
        frame = pd.DataFrame({"x": [1.0], "g": ["a"]})
        briefing = build_briefing(frame)
        assert briefing.rows == 1
        # Skewness is undefined for one observation; it must be absent, not zero.
        column = _named(briefing.numeric, "x")
        assert column is None or column.skewness is None

    def test_an_all_null_column_does_not_raise(self):
        frame = pd.DataFrame({"empty": [None, None, None], "x": [1.0, 2.0, 3.0]})
        briefing = build_briefing(frame)
        assert _named(briefing.missingness.columns, "empty").rate == pytest.approx(1.0)
        assert isinstance(render_briefing(briefing), str)

    def test_duplicate_column_names_are_reported_not_conflated(self):
        frame = pd.DataFrame([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], columns=["a", "a", "b"])
        briefing = build_briefing(frame)
        assert briefing.duplicate_column_names == ("a",)
        # The duplicated name is described once, from its first occurrence.
        assert len([c for c in briefing.numeric if c.column == "a"]) <= 1
        assert isinstance(render_briefing(briefing), str)

    def test_an_all_null_numeric_column_reports_no_shape(self):
        frame = pd.DataFrame({"x": pd.Series([None, None, None], dtype="float64")})
        assert _named(build_briefing(frame).numeric, "x") is None

    def test_the_input_frame_is_not_mutated(self, survey: pd.DataFrame):
        before = survey.copy(deep=True)
        build_briefing(survey)
        pd.testing.assert_frame_equal(survey, before)

    def test_briefing_text_never_raises(self, monkeypatch: pytest.MonkeyPatch):
        def explode(_df):
            raise RuntimeError("scan failed")

        monkeypatch.setattr("app.services.analysis_briefing.build_briefing", explode)
        # Context enrichment must not be able to fail an analysis.
        assert briefing_text(pd.DataFrame({"x": [1.0]})) == ""


class TestSerialization:
    def test_the_structured_briefing_is_json_safe(self, survey: pd.DataFrame):
        payload = build_briefing(survey).to_dict()
        round_tripped = json.loads(json.dumps(payload))
        assert round_tripped["rows"] == len(survey)
        assert any(w["column"] == "weight_final" for w in round_tripped["weights"])

    def test_the_briefing_is_immutable(self, survey: pd.DataFrame):
        briefing = build_briefing(survey)
        assert isinstance(briefing, DatasetBriefing)
        with pytest.raises(Exception):
            briefing.rows = 5  # type: ignore[misc]


class TestRenderedText:
    """Two facts whose whole value is that the model reads them."""

    def test_the_weight_column_is_named_in_the_text(self, survey: pd.DataFrame):
        text = render_briefing(build_briefing(survey))
        weight_lines = [line for line in text.splitlines() if "confidence" in line]
        assert any("weight_final" in line for line in weight_lines)
        # The same-named column with negative values is described as an ordinary
        # numeric column; what must not happen is its being offered as a weight.
        assert not any("weight_delta" in line for line in weight_lines)

    def test_the_minimum_group_size_is_stated_in_the_text(self, survey: pd.DataFrame):
        text = render_briefing(build_briefing(survey))
        arm_line = next(line for line in text.splitlines() if line.strip().startswith("arm"))
        assert "3 levels" in arm_line
        assert "2" in arm_line

    def test_the_text_states_the_row_and_column_count(self, survey: pd.DataFrame):
        text = render_briefing(build_briefing(survey))
        assert "300 rows" in text
        assert f"{len(survey.columns)} columns" in text
