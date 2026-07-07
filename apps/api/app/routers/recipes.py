"""Cleaning recipe endpoints — save, list, apply reusable cleaning templates."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.cleaning_recipe import CleaningRecipe
from app.models.dataset import Dataset
from app.models.job import Job
from app.schemas import CleaningRecipeResponse, CleaningStep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["recipes"])


class SaveRecipeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    job_id: uuid.UUID | None = None  # Save from an existing cleaning job
    steps: list[dict[str, Any]] | None = None  # Or provide steps directly


class ApplyRecipeRequest(BaseModel):
    dataset_id: uuid.UUID


@router.post("/", response_model=CleaningRecipeResponse, status_code=status.HTTP_201_CREATED)
async def save_recipe(
    body: SaveRecipeRequest,
    user: CurrentUser,
    db: DBSession,
) -> CleaningRecipeResponse:
    """Save a cleaning recipe (from a job or custom steps)."""
    steps = body.steps

    if body.job_id:
        # Extract steps from an existing cleaning job
        result = await db.execute(
            select(Job).where(Job.id == body.job_id, Job.user_id == user.id, Job.type == "clean")
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cleaning job not found"
            )
        if job.input_json and "steps" in job.input_json:
            steps = job.input_json["steps"]
        elif job.result_json and "steps" in job.result_json:
            steps = job.result_json["steps"]

    if not steps:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No steps provided. Either provide steps or a valid job_id.",
        )

    # Validate each step against the CleaningStep schema so corrupt LLM output
    # is rejected here rather than silently stored and discovered later on apply.
    try:
        validated_steps = [CleaningStep.model_validate(s).model_dump() for s in steps]
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"One or more steps failed schema validation: {exc}",
        ) from exc

    recipe = CleaningRecipe(
        id=uuid.uuid4(),
        user_id=user.id,
        name=body.name,
        description=body.description,
        steps_json={"steps": validated_steps},
    )
    db.add(recipe)
    await db.commit()
    await db.refresh(recipe)

    return CleaningRecipeResponse.model_validate(recipe)


@router.get("/", response_model=list[CleaningRecipeResponse])
async def list_recipes(
    user: CurrentUser,
    db: DBSession,
) -> list[CleaningRecipeResponse]:
    """List all cleaning recipes for the current user."""
    result = await db.execute(
        select(CleaningRecipe)
        .where(CleaningRecipe.user_id == user.id)
        .order_by(CleaningRecipe.created_at.desc())
    )
    recipes = result.scalars().all()
    return [CleaningRecipeResponse.model_validate(r) for r in recipes]


@router.get("/{recipe_id}", response_model=CleaningRecipeResponse)
async def get_recipe(
    recipe_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> CleaningRecipeResponse:
    """Get a single recipe."""
    result = await db.execute(
        select(CleaningRecipe).where(
            CleaningRecipe.id == recipe_id, CleaningRecipe.user_id == user.id
        )
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return CleaningRecipeResponse.model_validate(recipe)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> None:
    """Delete a recipe."""
    result = await db.execute(
        select(CleaningRecipe).where(
            CleaningRecipe.id == recipe_id, CleaningRecipe.user_id == user.id
        )
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    await db.delete(recipe)
    await db.commit()


@router.post("/{recipe_id}/apply")
async def apply_recipe(
    recipe_id: uuid.UUID,
    body: ApplyRecipeRequest,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    """Apply a saved recipe to a dataset — creates a new cleaning job."""
    from app.services.rate_limit import check_rate_limit, enforce_ai_budget

    await enforce_ai_budget(str(user.id))
    await check_rate_limit(str(user.id), action="recipe_apply", max_calls=30, window_seconds=3600)

    # Get recipe
    result = await db.execute(
        select(CleaningRecipe).where(
            CleaningRecipe.id == recipe_id, CleaningRecipe.user_id == user.id
        )
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    # Get dataset
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == body.dataset_id, Dataset.user_id == user.id)
    )
    dataset = ds_result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    steps = recipe.steps_json.get("steps", [])
    if not steps:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recipe has no steps")

    # Validate the recipe against THIS dataset's schema before dispatching, so a
    # recipe saved on a different schema fails fast (naming the offending column)
    # instead of silently no-opping or erroring mid-run.
    if dataset.status != "ready" or not dataset.profile_json:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dataset must be profiled before applying a recipe. "
            f"Current status: '{dataset.status}'",
        )

    from app.services.cleaning import supported_operations
    from app.services.plan_validator import validate_plan

    columns = list((dataset.profile_json.get("columns") or {}).keys())
    issues = validate_plan(steps, supported_operations(), columns)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Recipe is not compatible with this dataset.",
                "issues": [str(issue) for issue in issues],
            },
        )

    # Create a cleaning job
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=user.id,
        type="clean",
        status="pending",
        progress=0,
        input_json={"steps": steps, "recipe_id": str(recipe_id)},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    try:
        from app.tasks.cleaning_task import clean_dataset

        task = clean_dataset.delay(str(dataset.id), str(job.id), json.dumps(steps))
        job.celery_task_id = task.id
        await db.commit()
    except Exception as exc:
        logger.warning("Could not dispatch cleaning task: %s", exc)
        job.status = "failed"
        job.error_text = str(exc)
        await db.commit()

    return {
        "job_id": str(job.id),
        "recipe_name": recipe.name,
        "step_count": len(steps),
        "message": f"Applying recipe '{recipe.name}' to {dataset.filename}",
    }
