"""The scatter plotter — a chart on demand, with the chat pipeline's guarantees.

A plot request names its columns, so no planner is needed; but the line drawn
through the points is still a computed line, and it arrives with the same
provenance, denominators and code export as an answer from the chat. These
tests pin that: the plotter refuses what the validator refuses, reports what
it excluded, and never returns a figure it did not compute.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.analysis_executor import MAX_SCATTER_POINTS, SCATTER_SAMPLE_SEED
from app.services.analysis_plot import ScatterPlotError, scatter_plot, scatter_question


@pytest.fixture
def frame() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    n = 60
    x = np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "x": x,
            "y": 2 * x + rng.normal(0, 3, n),
            "region": np.array(["West", "East", "North"])[np.arange(n) % 3],
            "notes": [f"row {i}" for i in range(n)],
        }
    )


class TestScatterPlot:
    def test_returns_the_chat_contract(self, frame):
        out = scatter_plot(frame, x="x", y="y", filename="data.csv")
        assert set(out) == {"answer", "charts", "tables", "provenance"}
        chart = out["charts"][0]
        assert chart["chart_type"] == "scatter"
        assert len(chart["data"]) == 60
        assert chart["options"]["fit"]["slope"] == pytest.approx(2.0, abs=0.1)
        assert out["tables"][0]["columns"] == ["x", "y"]

    def test_provenance_records_the_operation_and_ships_code(self, frame):
        out = scatter_plot(frame, x="x", y="y", filename="data.csv")
        provenance = out["provenance"]
        assert provenance["dataset"] == {"filename": "data.csv", "rows": 60, "columns": 4}
        assert provenance["operations"][0]["op"] == "scatter_with_fit"
        assert provenance["operations"][0]["params"] == {"x": "x", "y": "y"}
        assert "linregress" in provenance["code"]["python"]
        assert "lm(" in provenance["code"]["r"]
        assert "language model" in provenance["methods_note"].lower()

    def test_answer_states_the_fit_and_the_denominator(self, frame):
        answer = scatter_plot(frame, x="x", y="y")["answer"]
        assert "60 complete rows" in answer
        assert "R²" in answer
        assert "y = " in answer

    def test_answer_reports_exclusions_and_sampling(self):
        n = 2_500
        x = np.arange(n, dtype=float)
        df = pd.DataFrame({"x": x, "y": x})
        df.loc[:9, "y"] = np.nan
        answer = scatter_plot(df, x="x", y="y")["answer"]
        assert "10 excluded" in answer
        assert "2,000" in answer and "2,490" in answer

    def test_colour_is_recorded_and_grouped(self, frame):
        out = scatter_plot(frame, x="x", y="y", color_by="region")
        assert out["provenance"]["operations"][0]["params"]["color_by"] == "region"
        assert out["charts"][0]["options"]["groups"] == ["East", "North", "West"]
        assert "region" in out["answer"]

    def test_answer_counts_groups_from_every_row_not_the_sample(self):
        n = MAX_SCATTER_POINTS * 5
        df = pd.DataFrame(
            {"x": np.arange(n, dtype=float), "y": np.arange(n, dtype=float), "g": "common"}
        )
        drawn = set(df.sample(n=MAX_SCATTER_POINTS, random_state=SCATTER_SAMPLE_SEED).index)
        left_out = next(index for index in df.index if index not in drawn)
        df.loc[left_out, "g"] = "rare"

        answer = scatter_plot(df, x="x", y="y", color_by="g")["answer"]
        assert "(2 groups)" in answer
        assert "rare" in answer

    def test_a_scatter_between_the_table_cap_and_the_sample_cap_has_one_row_note(self):
        n = 500
        df = pd.DataFrame({"x": np.arange(n, dtype=float), "y": np.arange(n, dtype=float)})
        notes = scatter_plot(df, x="x", y="y")["provenance"]["operations"][0]["notes"]
        assert sum("500" in note for note in notes) == 1

    def test_unknown_column_is_a_validation_error(self, frame):
        with pytest.raises(ScatterPlotError) as exc:
            scatter_plot(frame, x="nope", y="y")
        assert any("nope" in problem for problem in exc.value.problems)

    def test_text_column_is_a_validation_error(self, frame):
        with pytest.raises(ScatterPlotError) as exc:
            scatter_plot(frame, x="notes", y="y")
        assert any("not numeric" in problem for problem in exc.value.problems)

    def test_too_few_rows_is_reported_as_a_problem(self):
        df = pd.DataFrame({"x": [1.0, 2.0], "y": [1.0, 2.0]})
        with pytest.raises(ScatterPlotError) as exc:
            scatter_plot(df, x="x", y="y")
        assert "at least 3" in " ".join(exc.value.problems)

    def test_error_message_lists_every_problem(self, frame):
        with pytest.raises(ScatterPlotError) as exc:
            scatter_plot(frame, x="nope", y="notes")
        assert len(exc.value.problems) == 2
        assert "nope" in str(exc.value) and "notes" in str(exc.value)


class TestBubblePlot:
    def test_size_becomes_a_bubble_chart_and_is_named(self, frame):
        frame = frame.assign(orders=np.arange(len(frame), dtype=float) + 1)
        out = scatter_plot(frame, x="x", y="y", size="orders", color_by="region")
        chart = out["charts"][0]
        assert chart["chart_type"] == "bubble"
        assert chart["options"]["size_field"] == "orders"
        assert out["provenance"]["question"] == (
            "Scatter plot of y against x, colored by region, sized by orders"
        )
        assert "Bubble area shows orders" in out["answer"]

    def test_answer_ends_with_a_reading(self, frame):
        answer = scatter_plot(frame, x="x", y="y")["answer"]
        assert "Reading it:" in answer
        assert "positive" in answer
        # The significance sentence travels with the headline in both directions.
        assert "distinguishable from zero" in answer

    def test_answer_reading_says_when_the_slope_is_not_distinguishable(self):
        rng = np.random.default_rng(5)
        df = pd.DataFrame({"x": rng.normal(size=40), "y": rng.normal(size=40)})
        answer = scatter_plot(df, x="x", y="y")["answer"]
        assert "do not distinguish the slope from zero" in answer

    def test_chart_carries_the_reading_for_the_card(self, frame):
        reading = scatter_plot(frame, x="x", y="y")["charts"][0]["options"]["interpretation"]
        assert reading["summary"] and reading["caveats"] and reading["next_steps"]


class TestScatterQuestion:
    def test_names_the_axes(self):
        assert scatter_question("units", "revenue") == "Scatter plot of revenue against units"

    def test_names_the_colour(self):
        assert (
            scatter_question("units", "revenue", "region")
            == "Scatter plot of revenue against units, colored by region"
        )

    def test_names_the_size(self):
        assert (
            scatter_question("units", "revenue", size="orders")
            == "Scatter plot of revenue against units, sized by orders"
        )
