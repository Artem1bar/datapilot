"""Job reads and recipe CRUD/apply-validation against the real test database.

The jobs router only exposes GET /{job_id} (jobs are created by other
endpoints), so job rows are inserted via the ORM and read back through the
endpoint. The recipe apply test exercises the pre-dispatch 422 validation
path, which also hits the real Redis rate limiter.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

_TRIM_STEP = {
    "operation": "strip_whitespace",
    "column": "name",
    "params": {},
    "description": "Trim whitespace from name",
}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


async def test_get_job_round_trips_persisted_fields(client, db_session, test_user, make_dataset):
    from app.models.job import Job

    dataset = await make_dataset(test_user)
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=test_user.id,
        type="profile",
        status="running",
        progress=40,
        result_json={"note": "halfway"},
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.get(f"/api/v1/jobs/{job.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(job.id)
    assert body["dataset_id"] == str(dataset.id)
    assert body["type"] == "profile"
    assert body["status"] == "running"
    assert body["progress"] == 40
    assert body["result_json"] == {"note": "halfway"}
    assert body["created_at"] is not None


async def test_get_other_users_job_returns_404(client, db_session, other_user, make_dataset):
    from app.models.job import Job

    dataset = await make_dataset(other_user)
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=other_user.id,
        type="clean",
        status="pending",
        progress=0,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.get(f"/api/v1/jobs/{job.id}")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


async def test_recipe_create_list_get_delete(client, db_session, test_user):
    from app.models.cleaning_recipe import CleaningRecipe

    created = await client.post(
        "/api/v1/recipes/",
        json={"name": "Trim names", "description": "Whitespace cleanup", "steps": [_TRIM_STEP]},
    )
    assert created.status_code == 201
    recipe_id = created.json()["id"]

    # Steps validated and persisted as JSONB
    row = await db_session.execute(
        select(CleaningRecipe).where(CleaningRecipe.id == uuid.UUID(recipe_id))
    )
    recipe = row.scalar_one()
    assert recipe.user_id == test_user.id
    assert recipe.steps_json == {"steps": [_TRIM_STEP]}

    listed = await client.get("/api/v1/recipes/")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [recipe_id]

    got = await client.get(f"/api/v1/recipes/{recipe_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Trim names"
    assert got.json()["steps_json"] == {"steps": [_TRIM_STEP]}

    deleted = await client.delete(f"/api/v1/recipes/{recipe_id}")
    assert deleted.status_code == 204

    gone = await client.get(f"/api/v1/recipes/{recipe_id}")
    assert gone.status_code == 404
    row = await db_session.execute(
        select(CleaningRecipe).where(CleaningRecipe.id == uuid.UUID(recipe_id))
    )
    assert row.scalar_one_or_none() is None


async def test_recipe_create_without_steps_returns_400(client):
    resp = await client.post("/api/v1/recipes/", json={"name": "Empty recipe"})
    assert resp.status_code == 400


async def test_get_other_users_recipe_returns_404(client, db_session, other_user):
    from app.models.cleaning_recipe import CleaningRecipe

    recipe = CleaningRecipe(
        id=uuid.uuid4(),
        user_id=other_user.id,
        name="Not yours",
        steps_json={"steps": [_TRIM_STEP]},
    )
    db_session.add(recipe)
    await db_session.commit()

    resp = await client.get(f"/api/v1/recipes/{recipe.id}")

    assert resp.status_code == 404


async def test_apply_recipe_with_missing_column_returns_422(
    client, db_session, test_user, make_dataset
):
    from app.models.job import Job

    dataset = await make_dataset(
        test_user,
        status="ready",
        profile_json={
            "columns": {
                "name": {"dtype": "object"},
                "amount": {"dtype": "float64"},
            }
        },
    )
    bad_step = dict(_TRIM_STEP, column="not_a_column")
    created = await client.post(
        "/api/v1/recipes/", json={"name": "Wrong schema", "steps": [bad_step]}
    )
    assert created.status_code == 201
    recipe_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/recipes/{recipe_id}/apply", json={"dataset_id": str(dataset.id)}
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["message"] == "Recipe is not compatible with this dataset."
    assert any("not_a_column" in issue for issue in detail["issues"])
    # Validation failed before dispatch: no job row was created.
    jobs = await db_session.execute(select(Job).where(Job.dataset_id == dataset.id))
    assert jobs.scalars().all() == []
