from uuid import UUID, uuid4

import pytest

from notifications.application.errors import OrderContextMissing
from notifications.application.handle_event import HandleEvent, HandleResult
from notifications.domain.notification import NotificationStatus
from notifications.domain.order_projection import OrderStatus
from tests.fakes import FakeDatabase, FakeQueue, FakeUow
from tests.helpers import NOW, event, order_cancelled, order_created, order_paid, payment_created


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def handler(db: FakeDatabase, queue: FakeQueue) -> HandleEvent:
    return HandleEvent(lambda: FakeUow(db), queue, base_url="http://shop.test", clock=lambda: NOW)


async def test_order_created_stores_contact_and_summary_and_queues_a_notification(
    handler: HandleEvent, db: FakeDatabase, queue: FakeQueue
) -> None:
    incoming = order_created()

    assert await handler.handle(incoming) == HandleResult.PROCESSED

    order = db.orders[UUID(incoming.payload["order_id"])]
    assert order.contact.email == "maria@example.com"
    assert order.total_cents == 394_880
    assert len(order.items) == 2
    (notification,) = db.notifications.values()
    assert notification.kind.value == "ORDER_CREATED"
    assert notification.status is NotificationStatus.QUEUED
    assert notification.recipient.email == "maria@example.com"
    assert queue.enqueued == [notification.id]


async def test_duplicate_event_creates_a_single_notification_and_one_enqueue(
    handler: HandleEvent, db: FakeDatabase, queue: FakeQueue
) -> None:
    incoming = order_created()

    assert await handler.handle(incoming) == HandleResult.PROCESSED
    assert await handler.handle(incoming) == HandleResult.DUPLICATE

    assert len(db.notifications) == 1
    assert len(queue.enqueued) == 1


async def test_same_event_id_with_another_kind_is_still_a_distinct_notification(
    handler: HandleEvent, db: FakeDatabase
) -> None:
    incoming = order_created()
    await handler.handle(incoming)
    order_id = incoming.payload["order_id"]
    shared_id = uuid4()
    await handler.handle(payment_created(UUID(order_id), shared_id))
    await handler.handle(order_paid(UUID(order_id), uuid4()))

    assert db.by_kind() == ["ORDER_CREATED", "ORDER_PAID", "PIX_READY"]


async def test_full_order_lifecycle_builds_each_email_from_the_stored_context(
    handler: HandleEvent, db: FakeDatabase
) -> None:
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    await handler.handle(created)
    await handler.handle(payment_created(order_id))
    await handler.handle(order_paid(order_id))

    pix = next(n for n in db.notifications.values() if n.kind.value == "PIX_READY")
    assert pix.context["pix_code"] == "00020126PIXCODE5303986"
    assert pix.context["pix_expires_at"] == "2026-11-11T15:30:00+00:00"
    assert pix.recipient.name == "Maria da Silva"
    assert db.orders[order_id].status is OrderStatus.PAID
    assert db.orders[order_id].paid_at == NOW


@pytest.mark.parametrize(
    ("reason", "text"),
    [("out of stock", "estoque insuficiente"), ("payment expired", "o PIX expirou")],
)
async def test_cancellation_translates_the_reason(
    handler: HandleEvent, db: FakeDatabase, reason: str, text: str
) -> None:
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    await handler.handle(created)
    await handler.handle(order_cancelled(order_id, reason))

    cancelled = next(n for n in db.notifications.values() if n.kind.value == "ORDER_CANCELLED")
    assert cancelled.context["reason_text"] == text
    assert db.orders[order_id].status is OrderStatus.CANCELLED
    assert db.orders[order_id].cancel_reason == reason


async def test_event_before_order_created_is_retried_and_leaves_no_trace(
    handler: HandleEvent, db: FakeDatabase, queue: FakeQueue
) -> None:
    order_id = uuid4()
    early = payment_created(order_id)

    with pytest.raises(OrderContextMissing):
        await handler.handle(early)

    assert not db.notifications and not db.inbox and not queue.enqueued
    created = order_created(order_id=order_id)
    await handler.handle(created)
    assert await handler.handle(early) == HandleResult.PROCESSED
    assert db.by_kind() == ["ORDER_CREATED", "PIX_READY"]


async def test_unhandled_types_are_ignored(handler: HandleEvent, db: FakeDatabase) -> None:
    assert await handler.handle(event("StockReserved", uuid4())) == HandleResult.IGNORED
    assert not db.inbox


async def test_malformed_payload_is_skipped_without_blocking(
    handler: HandleEvent, db: FakeDatabase
) -> None:
    bad = order_created(email="not-an-email")
    assert await handler.handle(bad) == HandleResult.IGNORED
    assert not db.notifications and not db.inbox


async def test_enqueue_failure_after_commit_keeps_the_queued_notification(
    handler: HandleEvent, db: FakeDatabase, queue: FakeQueue
) -> None:
    queue.fail = True

    assert await handler.handle(order_created()) == HandleResult.PROCESSED

    (notification,) = db.notifications.values()
    assert notification.status is NotificationStatus.QUEUED
    assert queue.enqueued == []
