from datetime import timedelta
from uuid import UUID

import pytest

from notifications.application.handle_event import HandleEvent
from notifications.application.send_notification import SendNotification, SendStatus
from notifications.domain.notification import NotificationStatus
from notifications.domain.retry import RetryPolicy
from notifications.infrastructure.rendering.jinja import JinjaEmailRenderer
from tests.fakes import FakeDatabase, FakeQueue, FakeSender, FakeUow
from tests.helpers import NOW, order_cancelled, order_created, payment_created


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def sending(db: FakeDatabase, sender: FakeSender) -> SendNotification:
    return SendNotification(
        lambda: FakeUow(db),
        JinjaEmailRenderer(),
        sender,
        RetryPolicy(max_attempts=5, base_seconds=2),
        clock=lambda: NOW,
    )


async def queued_notification(db: FakeDatabase, kind: str = "ORDER_CREATED") -> UUID:
    handler = HandleEvent(lambda: FakeUow(db), FakeQueue(), clock=lambda: NOW)
    created = order_created()
    await handler.handle(created)
    order_id = UUID(created.payload["order_id"])
    if kind == "PIX_READY":
        await handler.handle(payment_created(order_id))
    if kind == "ORDER_CANCELLED":
        await handler.handle(order_cancelled(order_id, "payment expired"))
    return next(n.id for n in db.notifications.values() if n.kind.value == kind)


async def test_sends_the_rendered_email_to_the_customer_and_marks_it_sent(
    db: FakeDatabase, sender: FakeSender, sending: SendNotification
) -> None:
    notification_id = await queued_notification(db, "PIX_READY")

    outcome = await sending.execute(notification_id)

    assert outcome.status is SendStatus.SENT
    (email,) = sender.sent
    assert email.to_email == "maria@example.com"
    assert email.to_name == "Maria da Silva"
    assert email.subject.startswith("Seu PIX do pedido #")
    assert "00020126PIXCODE5303986" in email.html
    assert "00020126PIXCODE5303986" in email.text
    stored = db.notifications[notification_id]
    assert stored.status is NotificationStatus.SENT
    assert stored.sent_at == NOW
    assert stored.attempts == 1


async def test_running_the_task_twice_sends_a_single_email(
    db: FakeDatabase, sender: FakeSender, sending: SendNotification
) -> None:
    notification_id = await queued_notification(db)

    first = await sending.execute(notification_id)
    second = await sending.execute(notification_id)

    assert (first.status, second.status) == (SendStatus.SENT, SendStatus.SKIPPED)
    assert len(sender.sent) == 1


async def test_skips_when_another_worker_holds_the_row(
    db: FakeDatabase, sender: FakeSender, sending: SendNotification
) -> None:
    notification_id = await queued_notification(db)
    db.locked.add(notification_id)

    assert (await sending.execute(notification_id)).status is SendStatus.SKIPPED
    assert sender.sent == []


async def test_unknown_notification_is_skipped(sending: SendNotification) -> None:
    from uuid import uuid4

    assert (await sending.execute(uuid4())).status is SendStatus.SKIPPED


async def test_failure_schedules_a_retry_with_exponential_backoff(
    db: FakeDatabase, sender: FakeSender, sending: SendNotification
) -> None:
    notification_id = await queued_notification(db)
    sender.fail_times(3)

    delays = []
    for _ in range(3):
        outcome = await sending.execute(notification_id)
        assert outcome.status is SendStatus.RETRY
        delays.append(outcome.retry_in)

    assert delays == [2, 4, 8]
    stored = db.notifications[notification_id]
    assert stored.status is NotificationStatus.QUEUED
    assert stored.attempts == 3
    assert stored.next_attempt_at == NOW + timedelta(seconds=8)
    assert stored.last_error is not None and "smtp down" in stored.last_error

    assert (await sending.execute(notification_id)).status is SendStatus.SENT
    assert db.notifications[notification_id].attempts == 4


async def test_ends_in_failed_after_five_attempts_and_stops_retrying(
    db: FakeDatabase, sender: FakeSender, sending: SendNotification
) -> None:
    notification_id = await queued_notification(db)
    sender.fail_times(10)

    statuses = [(await sending.execute(notification_id)).status for _ in range(5)]

    assert statuses == [SendStatus.RETRY] * 4 + [SendStatus.FAILED]
    stored = db.notifications[notification_id]
    assert stored.status is NotificationStatus.FAILED
    assert stored.attempts == 5
    assert (await sending.execute(notification_id)).status is SendStatus.SKIPPED
    assert sender.sent == []


async def test_permanent_smtp_rejection_fails_immediately(
    db: FakeDatabase, sender: FakeSender, sending: SendNotification
) -> None:
    notification_id = await queued_notification(db)
    sender.fail_times(1, permanent=True)

    outcome = await sending.execute(notification_id)

    assert outcome.status is SendStatus.FAILED
    assert db.notifications[notification_id].status is NotificationStatus.FAILED
