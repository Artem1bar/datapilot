"""The preview endpoint reddens exactly the cells detection flagged.

Drives the real ``GET /datasets/{id}/preview`` handler over a real profile
produced by ``detect_quality_issues``, so the two halves of the grid
annotation — what the profiler decides and what the endpoint paints — are
checked against each other rather than in isolation.

The endpoint used to re-derive its own ``value > q75 * 3`` rule, which
disagreed with the profiler's fence in both directions: it reddened ordinary
high values, and on a column with a zero or negative q75 it reddened the
entire column.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.routers.datasets import preview_data
from app.tasks.profile_task import detect_quality_issues

USER_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()


def _profile_for(df: pd.DataFrame) -> dict:
    """Build the stored profile shape the endpoint reads."""
    return {
        "columns": {
            col: {
                "q25": float(df[col].quantile(0.25)),
                "q75": float(df[col].quantile(0.75)),
            }
            for col in df.columns
        },
        "data_quality": detect_quality_issues(df, domain="generic"),
    }


async def _preview(df: pd.DataFrame) -> dict:
    dataset = MagicMock()
    dataset.id = DATASET_ID
    dataset.user_id = USER_ID
    dataset.filename = "data.csv"
    dataset.r2_key = "key"
    dataset.profile_json = _profile_for(df)

    user = MagicMock()
    user.id = USER_ID

    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=dataset))

    with (
        patch("app.routers.datasets.download_file_bytes", return_value=b""),
        patch("app.routers.datasets.read_dataframe", return_value=df),
    ):
        return await preview_data(DATASET_ID, user, db)


def _outlier_rows(result: dict, column: str) -> set[int]:
    """Row indices the endpoint marked as outliers for *column*."""
    return {
        int(key.split(":", 1)[0])
        for key, annotations in result["cell_annotations"].items()
        if key.split(":", 1)[1] == column and any(a["type"] == "outlier" for a in annotations)
    }


@pytest.mark.asyncio
class TestPreviewOutlierAnnotations:
    async def test_marks_the_extreme_value_only(self):
        df = pd.DataFrame({"amount": [100.0, 110.0, 120.0, 130.0, 140.0, 99999.0]})
        result = await _preview(df)
        assert _outlier_rows(result, "amount") == {5}

    async def test_marks_a_low_outlier(self):
        df = pd.DataFrame({"price": [4000.0, 4100.0, 4200.0, 4300.0, 4400.0, 1.0]})
        result = await _preview(df)
        assert _outlier_rows(result, "price") == {5}, "low outliers were never surfaced"

    async def test_does_not_mark_ordinary_high_values(self):
        """A legitimate 600 among 50–200 expenses tripped the old ``q75 * 3`` rule.

        The 99999 is what puts the column into ``has_extreme_outliers``; without
        it the old rule was never reached and this would prove nothing. Stored
        q75 is 177.5, so the old cutoff sat at 532.5 and reddened the 600 too.
        """
        df = pd.DataFrame({"amount": [float(v) for v in range(50, 210, 10)] + [600.0, 99999.0]})
        assert df["amount"].quantile(0.75) * 3 < 600.0, "precondition: the old rule caught 600"
        result = await _preview(df)
        assert _outlier_rows(result, "amount") == {17}, "only the 99999 belongs in red"

    async def test_does_not_mark_every_cell_of_a_negative_column(self):
        """With a negative q75, ``value > q75 * 3`` was true for every normal cell.

        Worse, it was false for the one genuine outlier — the old rule reddened
        exactly the wrong six cells.
        """
        values = [-100.0, -95.0, -90.0, -85.0, -80.0, -75.0, -99999.0]
        df = pd.DataFrame({"balance": values})
        old_cutoff = df["balance"].quantile(0.75) * 3
        assert all(v > old_cutoff for v in values[:6]), "precondition: the old rule caught all six"
        assert not values[6] > old_cutoff, "precondition: the old rule missed the real outlier"

        result = await _preview(df)
        assert _outlier_rows(result, "balance") == {6}

    async def test_nulls_are_still_annotated_as_warnings(self):
        df = pd.DataFrame({"amount": [100.0, 110.0, None, 130.0, 140.0, 99999.0]})
        result = await _preview(df)
        null_rows = {
            int(key.split(":", 1)[0])
            for key, annotations in result["cell_annotations"].items()
            if any(a["type"] == "null" for a in annotations)
        }
        assert null_rows == {2}
