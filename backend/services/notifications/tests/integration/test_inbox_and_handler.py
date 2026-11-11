import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from notifications.application.errors import OrderContextMissing
from notifications.application.handle_event import HandleEvent, HandleResult
from notifications.domain.notification import NotificationStatus
from notifications.infrastructure.db.models import InboxMessageModel, NotificationModel
from tests.fakes import FakeQueue
from tests.helpers import NOW, order_cancelled, order_created, order_paid, payment_created
from tests.integration.helpers import all_notifications, count


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def handler(uow_factory, queue: FakeQueue) -> HandleEvent:
    return HandleEvent(uow_factory, queue, base_url="http://shop.test", clock=lambda: NOW)


async def test_duplicate_event_creates_exactly_one_notification(
    handler: HandleEvent, session_factory, queue: FakeQueue
) -> None:
    incoming = order_created()

    assert await handler.handle(incoming) == HandleResult.PROCESSED
    assert await handler.handle(incoming) == HandleResult.DUPLICATE

    assert await count(session_factory, NotificationModel) == 1
    assert await count(session_factory, InboxMessageModel) == 1
    assert len(queue.enqueued) == 1


async def test_concurrent_deliveries_of_the_same_event_create_one_notification(
    handler: HandleEvent, session_factory
) -> None:
    incoming = order_created()

    results = await asyncio.gather(*(handler.handle(incoming) for _ in range(6)))

    assert sorted(results).count(HandleResult.PROCESSED) == 1
    assert await count(session_factory, NotificationModel) == 1


async def test_handler_stores_queued_notification_and_inbox_in_one_transaction(
    handler: HandleEvent, session_factory, queue: FakeQueue
) -> None:
    incoming = order_created()
    await handler.handle(incoming)

    (stored,) = await all_notifications(session_factory)
    assert stored.status == NotificationStatus.QUEUED.value
    assert stored.kind == "ORDER_CREATED"
    assert stored.recipient_email == "maria@example.com"
    assert stored.subject.startswith("Recebemos o seu pedido #")
    assert stored.attempts == 0 and stored.sent_at is None
    assert queue.enqueued == [stored.id]


async def test_failure_before_commit_leaves_neither_notification_nor_inbox(
    handler: HandleEvent, session_factory, queue: FakeQueue
) -> None:
    early = payment_created(uuid4())

    with pytest.raises(OrderContextMissing):
        await handler.handle(early)

    assert await count(session_factory, NotificationModel) == 0
    assert await count(session_factory, InboxMessageModel) == 0
    assert queue.enqueued == []


async def test_full_lifecycle_keeps_one_notification_per_event_and_kind(
    handler: HandleEvent, session_factory
) -> None:
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    events = [
        created,
        payment_created(order_id),
        order_paid(order_id),
        order_cancelled(order_id, "payment expired"),
    ]
    for incoming in events + events:
        await handler.handle(incoming)

    kinds = sorted(n.kind for n in await all_notifications(session_factory))
    assert kinds == ["ORDER_CANCELLED", "ORDER_CREATED", "ORDER_PAID", "PIX_READY"]
    pix = next(n for n in await all_notifications(session_factory) if n.kind == "PIX_READY")
    assert pix.context["pix_code"] == "00020126PIXCODE5303986"
    assert pix.recipient_name == "Maria da Silva"


async def test_enqueue_outage_after_commit_keeps_the_row_queued(
    handler: HandleEvent, session_factory, queue: FakeQueue
) -> None:
    queue.fail = True

    assert await handler.handle(order_created()) == HandleResult.PROCESSED

    (stored,) = await all_notifications(session_factory)
    assert stored.status == "QUEUED"


async def test_daily_stats_are_computed_from_the_local_projection(
    handler: HandleEvent, uow_factory
) -> None:
    day_start = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
    ids = []
    for hours in (1, 2, 3):
        incoming = order_created(occurred_at=day_start + timedelta(hours=hours))
        await handler.handle(incoming)
        ids.append(UUID(incoming.payload["order_id"]))
    await handler.handle(order_paid(ids[0]))
    await handler.handle(order_cancelled(ids[1]))
    await handler.handle(order_created(occurred_at=day_start - timedelta(hours=1)))

    async with uow_factory() as uow:
        stats = await uow.orders.stats_between(day_start, day_start + timedelta(days=1))

    assert (stats.created, stats.paid, stats.cancelled) == (3, 1, 1)
    assert stats.paid_cents == 394_880
