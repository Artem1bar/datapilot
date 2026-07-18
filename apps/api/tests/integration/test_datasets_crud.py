"""Dataset CRUD round-trips through the real app and the real test database.

Rows are created directly via the ORM session (uploads need MinIO, which is
out of scope here); list/get/delete then go through the FastAPI endpoints with
only auth overridden.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select


async def test_list_returns_only_own_datasets(client, test_user, other_user, make_dataset):
    mine = await make_dataset(test_user, filename="mine.csv")
    await make_dataset(other_user, filename="theirs.csv")

    resp = await client.get("/api/v1/datasets/")

    assert resp.status_code == 200
    payload = resp.json()
    assert [d["id"] for d in payload] == [str(mine.id)]
    assert payload[0]["filename"] == "mine.csv"


async def test_get_dataset_round_trips_persisted_fields(client, test_user, make_dataset):
    profile = {"columns": {"name": {"dtype": "object", "null_pct": 0.25}}}
    dataset = await make_dataset(test_user, filename="roundtrip.csv", profile_json=profile)

    resp = await client.get(f"/api/v1/datasets/{dataset.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(dataset.id)
    assert body["filename"] == "roundtrip.csv"
    assert body["status"] == "uploaded"
    assert body["file_size_bytes"] == 1234
    # JSONB round-trip through the real engine's serializer
    assert body["profile_json"] == profile
    assert body["created_at"] is not None


async def test_get_unknown_dataset_returns_404(client):
    resp = await client.get(f"/api/v1/datasets/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_other_users_dataset_returns_404(client, db_session, other_user, make_dataset):
    from app.models.dataset import Dataset

    theirs = await make_dataset(other_user, filename="theirs.csv")

    resp = await client.get(f"/api/v1/datasets/{theirs.id}")

    assert resp.status_code == 404
    # Ownership check must not leak or delete the other user's row.
    row = await db_session.execute(select(Dataset).where(Dataset.id == theirs.id))
    assert row.scalar_one_or_none() is not None


async def test_delete_dataset_removes_dataset_and_jobs(client, db_session, test_user, make_dataset):
    from app.models.dataset import Dataset
    from app.models.job import Job

    dataset = await make_dataset(test_user)
    job = Job(
        id=uuid.uuid4(),
        dataset_id=dataset.id,
        user_id=test_user.id,
        type="profile",
        status="completed",
        progress=100,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/datasets/{dataset.id}")

    assert resp.status_code == 204
    gone = await db_session.execute(select(Dataset).where(Dataset.id == dataset.id))
    assert gone.scalar_one_or_none() is None
    jobs_left = await db_session.execute(select(Job).where(Job.dataset_id == dataset.id))
    assert jobs_left.scalars().all() == []


async def test_delete_other_users_dataset_returns_404(client, db_session, other_user, make_dataset):
    from app.models.dataset import Dataset

    theirs = await make_dataset(other_user)

    resp = await client.delete(f"/api/v1/datasets/{theirs.id}")

    assert resp.status_code == 404
    row = await db_session.execute(select(Dataset).where(Dataset.id == theirs.id))
    assert row.scalar_one_or_none() is not None
