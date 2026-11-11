import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import redis
from celery.contrib.testing.worker import start_worker

from notifications.application.handle_event import HandleEvent
from notifications.config import load_settings
from notifications.worker.celery_app import app as celery_app
from notifications.worker.queue import CeleryNotificationQueue
from tests.fakes import FakeQueue
from tests.helpers import order_created
from tests.integration.conftest import SmtpInbox
from tests.integration.helpers import age_notification, all_notifications, get_notification


def _redis_available() -> bool:
    try:
        return bool(redis.Redis.from_url(load_settings().celery_broker_url).ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable")


@pytest.fixture
def real_worker() -> Iterator[None]:
    queue_name = f"test-notifications-{uuid4().hex[:8]}"
    previous = (celery_app.conf.task_always_eager, celery_app.conf.task_default_queue)
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_default_queue = queue_name
    with start_worker(
        celery_app,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        queues=[queue_name],
        loglevel="WARNING",
        shutdown_timeout=20,
    ):
        yield
    celery_app.conf.task_always_eager, celery_app.conf.task_default_queue = previous
    client = redis.Redis.from_url(load_settings().celery_broker_url)
    client.delete(queue_name)


async def wait_for_status(session_factory, notification_id, status: str, timeout: float = 30.0):
    async with asyncio.timeout(timeout):
        while (await get_notification(session_factory, notification_id)).status != status:
            await asyncio.sleep(0.2)


async def test_a_real_worker_on_redis_delivers_the_email_enqueued_by_the_handler(
    uow_factory, session_factory, task_env: SmtpInbox, real_worker
) -> None:
    handler = HandleEvent(uow_factory, CeleryNotificationQueue())
    created = order_created(email="ana@example.com", name="Ana Paula")

    await handler.handle(created)
    (stored,) = await all_notifications(session_factory)
    await wait_for_status(session_factory, stored.id, "SENT")

    (mail,) = task_env.mails
    assert mail.rcpt_tos == ["ana@example.com"]
    assert mail.subject.startswith("Recebemos o seu pedido #")
    assert "Obrigado pela compra, Ana!" in mail.html
    assert (await get_notification(session_factory, stored.id)).sent_at is not None


async def test_a_real_worker_retries_with_backoff_until_the_smtp_recovers(
    uow_factory, session_factory, task_env: SmtpInbox, real_worker
) -> None:
    task_env.temporary_failures = 2
    await HandleEvent(uow_factory, CeleryNotificationQueue()).handle(order_created())
    (stored,) = await all_notifications(session_factory)

    await wait_for_status(session_factory, stored.id, "SENT")

    assert (await get_notification(session_factory, stored.id)).attempts == 3
    assert len(task_env.mails) == 1


async def test_the_requeue_task_runs_on_a_real_worker_and_recovers_a_lost_enqueue(
    uow_factory, session_factory, task_env: SmtpInbox, real_worker
) -> None:
    lost = FakeQueue()
    lost.fail = True
    await HandleEvent(uow_factory, lost).handle(order_created())
    (stored,) = await all_notifications(session_factory)
    await age_notification(session_factory, stored.id, datetime.now(UTC) - timedelta(minutes=5))

    from notifications.worker.tasks import requeue_stale_notifications

    result = await asyncio.to_thread(requeue_stale_notifications.delay)
    assert await asyncio.to_thread(result.get, timeout=30) == 1

    await wait_for_status(session_factory, stored.id, "SENT")
    assert len(task_env.mails) == 1
