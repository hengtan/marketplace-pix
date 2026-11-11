from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from notifications.config import Settings, load_settings

SEND_TASK = "notifications.send_notification"
REQUEUE_TASK = "notifications.requeue_stale_notifications"
DAILY_SUMMARY_TASK = "notifications.daily_sales_summary"


def create_celery_app(settings: Settings | None = None) -> Celery:
    settings = settings or load_settings()
    app = Celery(
        "notifications",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["notifications.worker.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone=settings.timezone,
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        result_expires=3600,
        beat_schedule={
            "requeue-stale-notifications": {
                "task": REQUEUE_TASK,
                "schedule": float(settings.requeue_interval_seconds),
            },
            "daily-sales-summary": {
                "task": DAILY_SUMMARY_TASK,
                "schedule": crontab(
                    hour=settings.daily_summary_hour, minute=settings.daily_summary_minute
                ),
            },
        },
    )
    return app


app = create_celery_app()
