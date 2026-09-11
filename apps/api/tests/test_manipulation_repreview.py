"""Re-previewing a chosen subset of manipulation operations.

The parse endpoint previews everything the AI proposed. Once a person can
exclude one of those operations, the before/after table it produced no longer
describes what would happen — so the card asks for a fresh preview of exactly
the operations still selected. Deterministic and AI-free, unlike parse.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi import HTTPException

from app.routers.manipulation import preview_operations
from app.schemas.manipulation import ManipulationApplyRequest

USER_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()

FRAME = pd.DataFrame(
    {
        "name": ["  Alice ", "Bob", "Cara"],
        "city": ["NYC", "LA", "NYC"],
        "amount": [10, 20, 30],
    }
)


def _dataset() -> MagicMock:
    dataset = MagicMock()
    dataset.id = DATASET_ID
    dataset.user_id = USER_ID
    dataset.filename = "people.csv"
    dataset.r2_key = "uploads/people.csv"
    dataset.profile_json = {"columns": {"name": {}, "city": {}, "amount": {}}}
    return dataset


def _db(dataset: MagicMock | None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = dataset
    db.execute.return_value = result
    return db


def _user() -> MagicMock:
    user = MagicMock()
    user.id = USER_ID
    return user


def _body(*ops: dict) -> ManipulationApplyRequest:
    return ManipulationApplyRequest.model_validate({"operations": list(ops)})


DELETE_CITY = {
    "op_type": "delete_columns",
    "params": {"columns": ["city"]},
    "description": "drop city",
}
RENAME_NAME = {
    "op_type": "rename_column",
    "params": {"old_name": "name", "new_name": "full_name"},
    "description": "rename name",
}


class TestPreviewOperations:
    @pytest.fixture(autouse=True)
    def _storage(self):
        """Stub the file read; the preview itself runs for real on FRAME."""
        with (
            patch("app.routers.manipulation.download_file_bytes", return_value=b"csv"),
            patch("app.routers.manipulation.read_dataframe", return_value=FRAME.copy()),
        ):
            yield

    @pytest.mark.asyncio
    async def test_previews_exactly_the_operations_given(self):
        preview = await preview_operations(DATASET_ID, _body(DELETE_CITY), _user(), _db(_dataset()))

        assert [op.op_type for op in preview.operations] == ["delete_columns"]
        assert "city" not in preview.preview_after[0]
        assert "city" in preview.preview_before[0]

    @pytest.mark.asyncio
    async def test_a_narrower_subset_produces_a_narrower_diff(self):
        """The failure this prevents: excluding an operation but still being
        shown the result of applying it."""
        both = await preview_operations(
            DATASET_ID, _body(DELETE_CITY, RENAME_NAME), _user(), _db(_dataset())
        )
        rename_only = await preview_operations(
            DATASET_ID, _body(RENAME_NAME), _user(), _db(_dataset())
        )

        assert "city" not in both.preview_after[0]
        assert "city" in rename_only.preview_after[0]
        assert "full_name" in rename_only.preview_after[0]

    @pytest.mark.asyncio
    async def test_makes_no_ai_call(self):
        with patch("app.services.manipulation.parse_manipulation_intent") as parse:
            await preview_operations(DATASET_ID, _body(DELETE_CITY), _user(), _db(_dataset()))
        parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_someone_elses_dataset_is_a_404(self):
        with pytest.raises(HTTPException) as exc:
            await preview_operations(DATASET_ID, _body(DELETE_CITY), _user(), _db(None))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_an_impossible_operation_is_a_422(self):
        bad = {
            "op_type": "delete_columns",
            "params": {"columns": ["not_a_column"]},
            "description": "drop a column that is not there",
        }
        with pytest.raises(HTTPException) as exc:
            await preview_operations(DATASET_ID, _body(bad), _user(), _db(_dataset()))
        assert exc.value.status_code == 422
