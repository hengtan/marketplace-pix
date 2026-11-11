import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from notifications.application.handle_event import HandleEvent
from notifications.worker.celery_app import app as celery_app
from notifications.worker.queue import CeleryNotificationQueue
from notifications.worker.tasks import (
    daily_sales_summary,
    requeue_stale_notifications,
    send_notification,
)
from tests.fakes import FakeQueue
from tests.helpers import order_cancelled, order_created, order_paid, payment_created
from tests.integration.conftest import SmtpInbox, free_port
from tests.integration.helpers import age_notification, all_notifications, get_notification


@pytest.fixture
def eager() -> Iterator[None]:
    previous = (
        celery_app.conf.task_always_eager,
        celery_app.conf.task_eager_propagates,
    )
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates = previous


ZONE = ZoneInfo("America/Sao_Paulo")


async def run_task(task, *args):
    return await asyncio.to_thread(lambda: task.apply(args=args).get())


@pytest.fixture
def handler(uow_factory, task_env, eager) -> HandleEvent:
    return HandleEvent(uow_factory, CeleryNotificationQueue(), base_url="http://shop.test")


async def test_handler_commits_queued_then_the_task_sends_the_email_over_smtp(
    handler: HandleEvent, session_factory, task_env: SmtpInbox
) -> None:
    created = order_created(email="maria@example.com", name="Maria da Silva")
    await handler.handle(created)

    (mail,) = task_env.mails
    assert mail.rcpt_tos == ["maria@example.com"]
    assert "Maria da Silva" in str(mail.message["To"])
    order_ref = created.payload["order_id"][:8].upper()
    assert mail.subject == f"Recebemos o seu pedido #{order_ref}"
    assert "Obrigado pela compra, Maria!" in mail.html
    assert "R$ 3.948,80" in mail.html
    assert "R$ 3.948,80" in mail.text
    assert mail.message.get_body(("html",)) is not None
    assert mail.message.get_body(("plain",)) is not None

    (stored,) = await all_notifications(session_factory)
    assert stored.status == "SENT"
    assert stored.sent_at is not None
    assert stored.attempts == 1


async def test_pix_email_carries_the_code_and_the_expiry(
    handler: HandleEvent, task_env: SmtpInbox
) -> None:
    created = order_created()
    await handler.handle(created)
    await handler.handle(payment_created(UUID(created.payload["order_id"])))

    pix = next(m for m in task_env.mails if m.subject.startswith("Seu PIX"))
    assert "00020126PIXCODE5303986" in pix.html
    assert "00020126PIXCODE5303986" in pix.text
    assert "11/11/2026 às 12:30" in pix.html


async def test_cancellation_email_has_the_friendly_reason(
    handler: HandleEvent, task_env: SmtpInbox
) -> None:
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    await handler.handle(created)
    await handler.handle(order_paid(order_id))
    await handler.handle(order_cancelled(order_id, "payment expired"))

    assert [m.subject.split(" #")[0] for m in task_env.mails] == [
        "Recebemos o seu pedido",
        "Pagamento confirmado para o pedido",
        "Seu pedido",
    ]
    assert "o PIX expirou" in task_env.mails[-1].html


async def test_running_the_task_twice_sends_one_email(
    handler: HandleEvent, session_factory, task_env: SmtpInbox
) -> None:
    await handler.handle(order_created())
    (stored,) = await all_notifications(session_factory)

    again = await run_task(send_notification, str(stored.id))

    assert again == "SKIPPED"
    assert len(task_env.mails) == 1


async def test_smtp_outage_retries_with_backoff_and_ends_in_failed(
    uow_factory, session_factory, task_env: SmtpInbox, eager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_PORT", str(free_port()))
    handler = HandleEvent(uow_factory, CeleryNotificationQueue())

    await handler.handle(order_created())

    (stored,) = await all_notifications(session_factory)
    assert stored.status == "FAILED"
    assert stored.attempts == 5
    assert stored.last_error is not None
    assert stored.sent_at is None
    assert task_env.mails == []


async def test_a_transient_smtp_error_is_retried_until_it_succeeds(
    handler: HandleEvent, session_factory, task_env: SmtpInbox
) -> None:
    task_env.temporary_failures = 2

    await handler.handle(order_created())

    (stored,) = await all_notifications(session_factory)
    assert stored.status == "SENT"
    assert stored.attempts == 3
    assert len(task_env.mails) == 1


async def test_permanent_smtp_rejection_fails_without_retrying(
    handler: HandleEvent, session_factory, task_env: SmtpInbox
) -> None:
    task_env.reject_recipients = True

    await handler.handle(order_created())

    (stored,) = await all_notifications(session_factory)
    assert stored.status == "FAILED"
    assert stored.attempts == 1


async def test_sweeper_requeues_old_queued_notifications_and_ignores_fresh_ones(
    uow_factory, session_factory, task_env: SmtpInbox, eager
) -> None:
    broken_queue = FakeQueue()
    broken_queue.fail = True
    handler = HandleEvent(uow_factory, broken_queue)
    old, fresh = order_created(), order_created(email="joao@example.com", name="Joao Souza")
    await handler.handle(old)
    await handler.handle(fresh)
    stored = {n.recipient_email: n for n in await all_notifications(session_factory)}
    assert task_env.mails == []
    await age_notification(
        session_factory, stored["maria@example.com"].id, datetime.now(UTC) - timedelta(minutes=5)
    )

    requeued = await run_task(requeue_stale_notifications)

    assert requeued == 1
    assert [m.rcpt_tos for m in task_env.mails] == [["maria@example.com"]]
    assert (
        await get_notification(session_factory, stored["maria@example.com"].id)
    ).status == "SENT"
    assert (
        await get_notification(session_factory, stored["joao@example.com"].id)
    ).status == "QUEUED"
    assert await run_task(requeue_stale_notifications) == 0


async def test_sweeper_does_not_touch_notifications_waiting_for_a_retry(
    uow_factory, session_factory, task_env: SmtpInbox, eager
) -> None:
    broken_queue = FakeQueue()
    broken_queue.fail = True
    await HandleEvent(uow_factory, broken_queue).handle(order_created())
    (stored,) = await all_notifications(session_factory)
    await age_notification(session_factory, stored.id, datetime.now(UTC) + timedelta(minutes=5))

    assert await run_task(requeue_stale_notifications) == 0
    assert task_env.mails == []


async def test_daily_summary_task_emails_the_admin(
    uow_factory, session_factory, task_env: SmtpInbox, eager
) -> None:
    handler = HandleEvent(uow_factory, FakeQueue())
    now = datetime.now(UTC)
    created = [order_created(occurred_at=now) for _ in range(3)]
    for incoming in created:
        await handler.handle(incoming)
    await handler.handle(order_paid(UUID(created[0].payload["order_id"])))
    await handler.handle(order_cancelled(UUID(created[1].payload["order_id"])))

    day = now.astimezone(ZONE).date().isoformat()
    result = await run_task(daily_sales_summary, day)

    assert result["created"] == 3 and result["paid"] == 1 and result["cancelled"] == 1
    (mail,) = task_env.mails
    assert mail.rcpt_tos == ["admin@shop.test"]
    assert mail.subject.startswith("Resumo de vendas de ")
    assert "R$ 3.948,80" in mail.html


def test_beat_schedule_requeues_every_30_seconds_and_summarises_daily() -> None:
    schedule = celery_app.conf.beat_schedule
    assert schedule["requeue-stale-notifications"]["schedule"] == 30.0
    assert (
        schedule["requeue-stale-notifications"]["task"]
        == "notifications.requeue_stale_notifications"
    )
    daily = schedule["daily-sales-summary"]
    assert daily["task"] == "notifications.daily_sales_summary"
    assert 55 in daily["schedule"].minute and 23 in daily["schedule"].hour
    assert celery_app.conf.timezone == "America/Sao_Paulo"
