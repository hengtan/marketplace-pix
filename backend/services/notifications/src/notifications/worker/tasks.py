from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from notifications.application.daily_summary import SendDailySalesSummary
from notifications.application.requeue_stale import RequeueStaleNotifications
from notifications.application.send_notification import SendNotification, SendStatus
from notifications.domain.retry import MAX_ATTEMPTS, RetryPolicy
from notifications.worker.celery_app import (
    DAILY_SUMMARY_TASK,
    REQUEUE_TASK,
    SEND_TASK,
    app,
)
from notifications.worker.queue import CeleryNotificationQueue
from notifications.worker.runtime import runtime

logger = logging.getLogger(__name__)


async def _send(notification_id: str) -> tuple[SendStatus, float | None]:
    async with runtime() as rt:
        policy = RetryPolicy(max_attempts=MAX_ATTEMPTS, base_seconds=rt.settings.retry_base_seconds)
        outcome = await SendNotification(rt.uow_factory, rt.renderer, rt.sender, policy).execute(
            UUID(notification_id)
        )
    return outcome.status, outcome.retry_in


def send_notification_task(self: Any, notification_id: str) -> str:
    status, retry_in = asyncio.run(_send(notification_id))
    if status is SendStatus.RETRY:
        raise self.retry(countdown=retry_in, exc=RuntimeError("e-mail delivery failed, retrying"))
    return status.value


async def _requeue() -> int:
    async with runtime() as rt:
        return await RequeueStaleNotifications(
            rt.uow_factory,
            CeleryNotificationQueue(),
            stale_after=timedelta(seconds=rt.settings.requeue_after_seconds),
        ).execute()


def requeue_stale_notifications_task() -> int:
    requeued = asyncio.run(_requeue())
    if requeued:
        logger.info("requeued %s stale notifications", requeued)
    return requeued


async def _daily_summary(day: str | None) -> dict[str, Any]:
    async with runtime() as rt:
        summary = await SendDailySalesSummary(
            rt.uow_factory,
            rt.renderer,
            rt.sender,
            rt.settings.admin_email,
            rt.settings.timezone,
        ).execute(date.fromisoformat(day) if day else None)
    stats = summary.stats
    return {
        "day": summary.day.isoformat(),
        "created": stats.created,
        "paid": stats.paid,
        "cancelled": stats.cancelled,
        "paid_cents": stats.paid_cents,
    }


def daily_sales_summary_task(day: str | None = None) -> dict[str, Any]:
    return asyncio.run(_daily_summary(day))


send_notification = app.task(bind=True, name=SEND_TASK, max_retries=MAX_ATTEMPTS, acks_late=True)(
    send_notification_task
)
requeue_stale_notifications = app.task(name=REQUEUE_TASK)(requeue_stale_notifications_task)
daily_sales_summary = app.task(name=DAILY_SUMMARY_TASK)(daily_sales_summary_task)
