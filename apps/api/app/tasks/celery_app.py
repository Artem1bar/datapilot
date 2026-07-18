"""Celery application factory."""

from celery import Celery

from app.config import settings


def create_celery_app() -> Celery:
    """Build and configure the Celery application."""
    app = Celery(
        "datapilot",
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,
    )

    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # Auto-discover tasks from app.tasks package
        imports=[
            "app.tasks.profile_task",
            "app.tasks.cleaning_task",
            "app.tasks.export_task",
            "app.tasks.cleanup_task",
        ],
        beat_schedule={
            "cleanup-orphaned-storage-daily": {
                "task": "cleanup_orphaned_storage",
                "schedule": 24 * 60 * 60,  # once a day
            },
            "purge-expired-exports-daily": {
                "task": "purge_expired_exports",
                "schedule": 24 * 60 * 60,  # once a day
            },
            # Fail jobs orphaned by a worker crash/restart so clients stop
            # polling; Redis may still redeliver the task later (acks_late),
            # in which case the job simply completes on the second attempt.
            "reap-stale-jobs": {
                "task": "reap_stale_jobs",
                "schedule": 10 * 60,  # every 10 minutes
            },
        },
    )

    return app


celery_app = create_celery_app()
