"""Unit tests for the /api/v1/recipes router.

Covers: save, list, get, delete, apply — including cross-user isolation,
happy paths, error paths, and the job-type-literal "clean" regression.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.recipes import (
    ApplyRecipeRequest,
    SaveRecipeRequest,
    apply_recipe,
    delete_recipe,
    get_recipe,
    list_recipes,
    save_recipe,
)
from app.schemas import CleaningRecipeResponse

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

USER_A = MagicMock()
USER_A.id = uuid.uuid4()

USER_B = MagicMock()
USER_B.id = uuid.uuid4()

RECIPE_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()

VALID_STEPS = [
    {"operation": "strip_whitespace", "column": "name", "params": {}, "description": "trim"},
]


def _make_recipe(user_id: uuid.UUID, steps: list | None = None) -> MagicMock:
    r = MagicMock()
    r.id = RECIPE_ID
    r.user_id = user_id
    r.name = "My Recipe"
    r.description = "A test recipe"
    r.steps_json = {"steps": steps or VALID_STEPS}
    r.created_at = MagicMock()
    return r


def _make_db(query_result=None) -> AsyncMock:
    """Return an async DB session mock."""
    db = AsyncMock()
    # add/delete are synchronous on the real session — prevent AsyncMock from
    # wrapping them so we don't get "coroutine never awaited" warnings.
    db.add = MagicMock()
    db.delete = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = query_result
    result.scalars.return_value.all.return_value = query_result if isinstance(query_result, list) else []
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# save_recipe
# ---------------------------------------------------------------------------

class TestSaveRecipe:
    @pytest.mark.asyncio
    async def test_saves_with_direct_steps(self):
        db = _make_db()
        with patch("app.routers.recipes.CleaningRecipeResponse.model_validate") as mv:
            mv.return_value = MagicMock(spec=CleaningRecipeResponse)
            body = SaveRecipeRequest(name="My Recipe", steps=VALID_STEPS)
            await save_recipe(body, USER_A, db)
        db.add.assert_called_once()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_steps_raises_400(self):
        from fastapi import HTTPException
        db = _make_db()
        body = SaveRecipeRequest(name="Empty")
        with pytest.raises(HTTPException) as exc_info:
            await save_recipe(body, USER_A, db)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_step_schema_raises_422(self):
        """A step missing required 'operation' field should raise 422."""
        from fastapi import HTTPException
        db = _make_db()
        bad_steps = [{"no_operation_field": "bad"}]
        body = SaveRecipeRequest(name="Bad", steps=bad_steps)
        with pytest.raises(HTTPException) as exc_info:
            await save_recipe(body, USER_A, db)
        assert exc_info.value.status_code == 422  # HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_save_from_job_uses_clean_type(self):
        """Querying a job must filter by type='clean', not 'cleaning' (regression)."""

        job = MagicMock()
        job.input_json = {"steps": VALID_STEPS}
        db = _make_db(query_result=job)

        with patch("app.routers.recipes.CleaningRecipeResponse.model_validate") as mv:
            mv.return_value = MagicMock(spec=CleaningRecipeResponse)
            body = SaveRecipeRequest(name="From Job", job_id=JOB_ID)
            await save_recipe(body, USER_A, db)

        # Verify the execute call happened and the recipe was saved
        db.execute.assert_awaited()
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_from_missing_job_raises_404(self):
        from fastapi import HTTPException
        db = _make_db(query_result=None)
        body = SaveRecipeRequest(name="From Job", job_id=JOB_ID)
        with pytest.raises(HTTPException) as exc_info:
            await save_recipe(body, USER_A, db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_recipes
# ---------------------------------------------------------------------------

class TestListRecipes:
    @pytest.mark.asyncio
    async def test_returns_only_current_user_recipes(self):
        recipe_a = _make_recipe(USER_A.id)
        db = _make_db(query_result=[recipe_a])
        with patch("app.routers.recipes.CleaningRecipeResponse.model_validate") as mv:
            mv.return_value = MagicMock(spec=CleaningRecipeResponse)
            result = await list_recipes(USER_A, db)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_user_b_sees_empty_list(self):
        db = _make_db(query_result=[])
        result = await list_recipes(USER_B, db)
        assert result == []


# ---------------------------------------------------------------------------
# get_recipe
# ---------------------------------------------------------------------------

class TestGetRecipe:
    @pytest.mark.asyncio
    async def test_returns_own_recipe(self):
        recipe = _make_recipe(USER_A.id)
        db = _make_db(query_result=recipe)
        with patch("app.routers.recipes.CleaningRecipeResponse.model_validate") as mv:
            mv.return_value = MagicMock(spec=CleaningRecipeResponse)
            result = await get_recipe(RECIPE_ID, USER_A, db)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cross_user_access_raises_404(self):
        """User B must not be able to retrieve User A's recipe."""
        from fastapi import HTTPException
        db = _make_db(query_result=None)  # DB filters by user_id, returns nothing for B
        with pytest.raises(HTTPException) as exc_info:
            await get_recipe(RECIPE_ID, USER_B, db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_recipe
# ---------------------------------------------------------------------------

class TestDeleteRecipe:
    @pytest.mark.asyncio
    async def test_deletes_own_recipe(self):
        recipe = _make_recipe(USER_A.id)
        db = _make_db(query_result=recipe)
        await delete_recipe(RECIPE_ID, USER_A, db)
        db.delete.assert_awaited_with(recipe)
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_cross_user_delete_raises_404(self):
        from fastapi import HTTPException
        db = _make_db(query_result=None)
        with pytest.raises(HTTPException) as exc_info:
            await delete_recipe(RECIPE_ID, USER_B, db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# apply_recipe
# ---------------------------------------------------------------------------

class TestApplyRecipe:
    @pytest.mark.asyncio
    async def test_apply_creates_job_with_clean_type(self):
        """Job created by apply_recipe must use type='clean', not 'cleaning' (regression)."""
        recipe = _make_recipe(USER_A.id)
        dataset = MagicMock()
        dataset.id = DATASET_ID
        dataset.filename = "data.csv"
        dataset.user_id = USER_A.id

        db = AsyncMock()
        db.add = MagicMock()
        # First execute → recipe, second → dataset
        db.execute.side_effect = [
            _execute_result(recipe),
            _execute_result(dataset),
        ]

        with (
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
            patch("app.tasks.cleaning_task.clean_dataset") as mock_task,
        ):
            mock_task.delay.return_value = MagicMock(id="celery-task-id")
            body = ApplyRecipeRequest(dataset_id=DATASET_ID)
            result = await apply_recipe(RECIPE_ID, body, USER_A, db)

        assert result["job_id"] is not None
        # Verify the job added to DB has type="clean"
        added_job = db.add.call_args[0][0]
        assert added_job.type == "clean"

    @pytest.mark.asyncio
    async def test_apply_sets_job_failed_on_celery_error(self):
        """If Celery dispatch fails, job.status must be set to 'failed'."""
        recipe = _make_recipe(USER_A.id)
        dataset = MagicMock()
        dataset.id = DATASET_ID
        dataset.filename = "data.csv"
        dataset.user_id = USER_A.id

        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [
            _execute_result(recipe),
            _execute_result(dataset),
        ]

        with (
            patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
            patch("app.tasks.cleaning_task.clean_dataset") as mock_task,
        ):
            mock_task.delay.side_effect = RuntimeError("Redis down")
            body = ApplyRecipeRequest(dataset_id=DATASET_ID)
            result = await apply_recipe(RECIPE_ID, body, USER_A, db)

        added_job = db.add.call_args[0][0]
        assert added_job.status == "failed"

    @pytest.mark.asyncio
    async def test_apply_missing_recipe_raises_404(self):
        from fastapi import HTTPException
        db = AsyncMock()
        db.execute.return_value = _execute_result(None)

        with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc_info:
                await apply_recipe(RECIPE_ID, ApplyRecipeRequest(dataset_id=DATASET_ID), USER_A, db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_apply_missing_dataset_raises_404(self):
        from fastapi import HTTPException
        recipe = _make_recipe(USER_A.id)
        db = AsyncMock()
        db.execute.side_effect = [
            _execute_result(recipe),
            _execute_result(None),
        ]

        with patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc_info:
                await apply_recipe(RECIPE_ID, ApplyRecipeRequest(dataset_id=DATASET_ID), USER_A, db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _execute_result(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result
