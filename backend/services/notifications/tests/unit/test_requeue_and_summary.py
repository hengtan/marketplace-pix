from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from notifications.application.daily_summary import SendDailySalesSummary
from notifications.application.errors import NotificationNotFound
from notifications.application.handle_event import HandleEvent
from notifications.application.queries import ListNotifications, PreviewNotification
from notifications.application.requeue_stale import RequeueStaleNotifications
from notifications.domain.notification import NotificationStatus
from notifications.infrastructure.rendering.jinja import JinjaEmailRenderer
from tests.fakes import FakeDatabase, FakeQueue, FakeSender, FakeUow
from tests.helpers import (
    CUSTOMER_ID,
    NOW,
    order_cancelled,
    order_created,
    order_paid,
    payment_created,
)


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


async def seed_order_created(db: FakeDatabase, at: datetime, **kwargs: object) -> UUID:
    handler = HandleEvent(lambda: FakeUow(db), FakeQueue(), clock=lambda: at)
    incoming = order_created(occurred_at=at, **kwargs)  # type: ignore[arg-type]
    await handler.handle(incoming)
    return UUID(incoming.payload["order_id"])


async def test_sweep_requeues_only_stale_queued_notifications(db: FakeDatabase) -> None:
    old = await seed_order_created(db, NOW - timedelta(minutes=10))
    await seed_order_created(db, NOW - timedelta(seconds=5))
    sent = await seed_order_created(db, NOW - timedelta(minutes=20))
    for n in db.notifications.values():
        if n.order_id == sent:
            n.status = NotificationStatus.SENT
    queue = FakeQueue()
    sweep = RequeueStaleNotifications(
        lambda: FakeUow(db), queue, stale_after=timedelta(seconds=60), clock=lambda: NOW
    )

    assert await sweep.execute() == 1

    stale_id = next(n.id for n in db.notifications.values() if n.order_id == old)
    assert queue.enqueued == [stale_id]


async def test_sweep_does_not_requeue_the_same_notification_on_the_next_run(
    db: FakeDatabase,
) -> None:
    await seed_order_created(db, NOW - timedelta(minutes=10))
    queue = FakeQueue()
    sweep = RequeueStaleNotifications(
        lambda: FakeUow(db), queue, stale_after=timedelta(seconds=60), clock=lambda: NOW
    )

    assert await sweep.execute() == 1
    assert await sweep.execute() == 0


async def test_sweep_respects_the_backoff_of_notifications_waiting_for_a_retry(
    db: FakeDatabase,
) -> None:
    await seed_order_created(db, NOW - timedelta(minutes=10))
    (notification,) = db.notifications.values()
    notification.next_attempt_at = NOW + timedelta(seconds=30)
    queue = FakeQueue()
    sweep = RequeueStaleNotifications(lambda: FakeUow(db), queue, clock=lambda: NOW)

    assert await sweep.execute() == 0


async def test_sweep_survives_a_broker_outage(db: FakeDatabase) -> None:
    await seed_order_created(db, NOW - timedelta(minutes=10))
    queue = FakeQueue()
    queue.fail = True
    sweep = RequeueStaleNotifications(lambda: FakeUow(db), queue, clock=lambda: NOW)

    assert await sweep.execute() == 0


async def test_daily_summary_counts_the_day_and_emails_the_admin(db: FakeDatabase) -> None:
    day_start = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
    handler = HandleEvent(lambda: FakeUow(db), FakeQueue(), clock=lambda: NOW)
    ids = []
    for hours in (1, 2, 3):
        incoming = order_created(occurred_at=day_start + timedelta(hours=hours))
        await handler.handle(incoming)
        ids.append(UUID(incoming.payload["order_id"]))
    await handler.handle(order_paid(ids[0]))
    await handler.handle(order_paid(ids[1]))
    await handler.handle(order_cancelled(ids[2]))
    yesterday = order_created(occurred_at=day_start - timedelta(hours=2))
    await handler.handle(yesterday)
    sender = FakeSender()
    summary = SendDailySalesSummary(
        lambda: FakeUow(db),
        JinjaEmailRenderer(),
        sender,
        "admin@shop.test",
        clock=lambda: datetime(2026, 11, 11, 23, 55, tzinfo=UTC) - timedelta(hours=3),
    )

    result = await summary.execute()

    assert result.day == date(2026, 11, 11)
    assert (result.stats.created, result.stats.paid, result.stats.cancelled) == (3, 2, 1)
    assert result.stats.paid_cents == 2 * 394_880
    (email,) = sender.sent
    assert email.to_email == "admin@shop.test"
    assert email.subject == "Resumo de vendas de 11/11/2026"
    assert "R$ 7.897,60" in email.html


async def test_list_and_preview(db: FakeDatabase) -> None:
    order_id = await seed_order_created(db, NOW)
    other = await seed_order_created(db, NOW, customer_id=uuid4())
    listing = ListNotifications(lambda: FakeUow(db))

    items, total = await listing.execute(CUSTOMER_ID, 1, 20)
    assert total == 1 and items[0].order_id == order_id
    everything, total_all = await listing.execute(None, 1, 1)
    assert total_all == 2 and len(everything) == 1
    assert other != order_id

    preview = PreviewNotification(lambda: FakeUow(db), JinjaEmailRenderer())
    html = await preview.execute(items[0].id)
    assert "<!doctype html>" in html and "Maria" in html
    with pytest.raises(NotificationNotFound):
        await preview.execute(uuid4())


async def test_pix_ready_is_listed_after_payment_created(db: FakeDatabase) -> None:
    handler = HandleEvent(lambda: FakeUow(db), FakeQueue(), clock=lambda: NOW)
    created = order_created()
    await handler.handle(created)
    await handler.handle(payment_created(UUID(created.payload["order_id"])))
    items, total = await ListNotifications(lambda: FakeUow(db)).execute(CUSTOMER_ID, 1, 20)
    assert total == 2
