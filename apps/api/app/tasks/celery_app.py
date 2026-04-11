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
        ],
    )

    return app


celery_app = create_celery_app()
