"""One real Celery task, eager mode, against the real test database.

``reap_stale_jobs`` is the only task with no storage dependency: it runs on
the synchronous engine (``app.tasks._db``), which derives a psycopg2 URL from
the same ``settings.DATABASE_URL`` the async engine uses — so eager execution
in-process hits the same ``datapilot_test`` database as the fixtures.

Stale rows are inserted with DB-side clock arithmetic (``now() - interval``)
because the task compares ``created_at`` against ``func.now()`` — mixing in
the test process's clock/timezone could misfire.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

_INSERT_JOB = text(
    """
    INSERT INTO jobs (id, dataset_id, user_id, type, status, progress, created_at)
    VALUES (:id, :dataset_id, :user_id, :type, :status, :progress,
            now() - make_interval(mins => :age_minutes))
    """
)


async def _insert_job(db_session, *, dataset, user, status: str, age_minutes: int) -> uuid.UUID:
    job_id = uuid.uuid4()
    await db_session.execute(
        _INSERT_JOB,
        {
            "id": job_id,
            "dataset_id": dataset.id,
            "user_id": user.id,
            "type": "clean",
            "status": status,
            "progress": 10,
            "age_minutes": age_minutes,
        },
    )
    await db_session.commit()
    return job_id


async def test_reap_stale_jobs_fails_old_rows_and_spares_fresh_ones(
    db_session, test_user, make_dataset
):
    from app.models.job import Job
    from app.tasks.celery_app import celery_app
    from app.tasks.cleanup_task import _STALE_JOB_MESSAGE, reap_stale_jobs

    dataset = await make_dataset(test_user)
    stale_running = await _insert_job(
        db_session, dataset=dataset, user=test_user, status="running", age_minutes=120
    )
    stale_pending = await _insert_job(
        db_session, dataset=dataset, user=test_user, status="pending", age_minutes=45
    )
    fresh_pending = await _insert_job(
        db_session, dataset=dataset, user=test_user, status="pending", age_minutes=0
    )
    old_completed = await _insert_job(
        db_session, dataset=dataset, user=test_user, status="completed", age_minutes=120
    )

    previous_eager = celery_app.conf.task_always_eager
    previous_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        result = reap_stale_jobs.delay(max_age_minutes=30)
        assert result.successful()
        assert result.get() == {"reaped": 2}
    finally:
        celery_app.conf.task_always_eager = previous_eager
        celery_app.conf.task_eager_propagates = previous_propagates

    rows = await db_session.execute(select(Job))
    jobs = {job.id: job for job in rows.scalars().all()}

    for job_id in (stale_running, stale_pending):
        assert jobs[job_id].status == "failed"
        assert jobs[job_id].error_text == _STALE_JOB_MESSAGE
        assert jobs[job_id].completed_at is not None

    assert jobs[fresh_pending].status == "pending"
    assert jobs[fresh_pending].error_text is None
    assert jobs[old_completed].status == "completed"
    assert jobs[old_completed].error_text is None
